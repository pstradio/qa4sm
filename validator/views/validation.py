from datetime import datetime
import logging
from multiprocessing import Process
from re import sub as regex_subs

from dateutil.tz import tzlocal
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import connections
from django.forms import formset_factory
from django.forms.models import ModelMultipleChoiceField
from django.http.response import HttpResponse
from django.http.response import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template import loader

from validator.forms import DatasetConfigurationForm, FilterCheckboxSelectMultiple,\
    ValidationRunForm, ParamFilterChoiceField, ParamFilterSelectMultiple
from validator.models import DataFilter, DatasetVersion, DataVariable
from validator.models import Dataset
from validator.models import Settings
from validator.models import ValidationRun, DatasetConfiguration
from validator.models import ISMNNetworks
from validator.validation import run_validation
import validator.validation.globals as val_globals
from validator.validation.validation import stop_running_validation
from django.db.models import Case, When
from django.urls import reverse

# see https://docs.djangoproject.com/en/2.1/topics/forms/formsets/
DatasetConfigurationFormSet = formset_factory(DatasetConfigurationForm, extra=0, max_num=5, min_num=1, validate_max=True, validate_min=True)


def _compare_param_filters(new_param_filters, old_param_filters):
    """
    Checking if parametrised filters are the same for given configuration, checks till finds the first failure
    or till the end of the list.

    If lengths of queries do not agree then return False.
    """
    if len(new_param_filters) != len(old_param_filters):
        return False
    else:
        ind = 0
        max_ind = len(new_param_filters)
        is_the_same = True
        while ind < max_ind and new_param_filters[ind].parameters == old_param_filters[ind].parameters:
            ind += 1
        if ind != len(new_param_filters):
            is_the_same = False

    return is_the_same


def _compare_filters(new_dataset, old_dataset):
    """
    Checking if filters are the same for given configuration, checks till finds the first failure or till the end
     of the list. If filters are the same, then parameterised filters are checked.

    If lengths of queries do not agree then return False.
    """

    new_run_filters = new_dataset.filters.all().order_by('name')
    old_run_filters = old_dataset.filters.all().order_by('name')
    new_filts_len = len(new_run_filters)
    old_filts_len = len(old_run_filters)

    if new_filts_len != old_filts_len:
        return False
    elif new_filts_len == old_filts_len == 0:
        is_the_same = True
        new_param_filters = new_dataset.parametrisedfilter_set.all().order_by('filter_id')
        if len(new_param_filters) != 0:
            old_param_filters = old_dataset.parametrisedfilter_set.all().order_by('filter_id')
            is_the_same = _compare_param_filters(new_param_filters, old_param_filters)
        return is_the_same
    else:
        filt_ind = 0
        max_filt_ind = new_filts_len

        while filt_ind < max_filt_ind and new_run_filters[filt_ind] == old_run_filters[filt_ind]:
            filt_ind += 1

        if filt_ind == max_filt_ind:
            is_the_same = True
            new_param_filters = new_dataset.parametrisedfilter_set.all().order_by('filter_id')
            if len(new_param_filters) != 0:
                old_param_filters = old_dataset.parametrisedfilter_set.all().order_by('filter_id')
                is_the_same = _compare_param_filters(new_param_filters, old_param_filters)
        else:
            is_the_same = False
    return is_the_same


def _compare_datasets(new_run_config, old_run_config):
    """
    Takes queries of dataset configurations and compare datasets one by one. If names and versions agree,
    checks filters.

    Runs till the first failure or til the end of the configuration list.
    If lengths of queries do not agree then return False.
    """
    new_len = len(new_run_config)

    if len(old_run_config) != new_len:
        return False
    else:
        ds_fields = val_globals.DS_FIELDS
        max_ds_ind = len(ds_fields)
        the_same = True
        conf_ind = 0

        while conf_ind < new_len and the_same:
            ds_ind = 0
            new_dataset = new_run_config[conf_ind]
            old_dataset = old_run_config[conf_ind]
            while ds_ind < max_ds_ind and getattr(new_dataset, ds_fields[ds_ind]) == getattr(old_dataset, ds_fields[ds_ind]):
                ds_ind += 1
            if ds_ind == max_ds_ind:
                the_same = _compare_filters(new_dataset, old_dataset)
            else:
                the_same = False
            conf_ind += 1
    return the_same


def _check_scaling_method(new_run, old_run):
    """
    It takes two validation runs and compares scaling method together with the scaling reference dataset.

    """
    new_run_sm = new_run.scaling_method
    if new_run_sm != old_run.scaling_method:
        return False
    else:
        if new_run_sm != 'none':
            try:
                new_scal_ref = DatasetConfiguration.objects.get(pk=new_run.scaling_ref_id).dataset
                run_scal_ref = DatasetConfiguration.objects.get(pk=old_run.scaling_ref_id).dataset
                if new_scal_ref != run_scal_ref:
                    return False
            except:
                return False
    return True


def _compare_validation_runs(new_run, runs_set, user):
    """
    Compares two validation runs. It takes a new_run and checks the query given by runs_set according to parameters
    given in the vr_fileds. If all fields agree it checks datasets configurations.

    It works till the first found validation run or till the end of the list.

    Returns a dict:
         {
        'is_there_validation': is_the_same,
        'val_id': val_id
        }
        where is_the_same migh be True or False and val_id might be None or the appropriate id ov a validation run
    """
    vr_fields = val_globals.VR_FIELDS
    is_the_same = False # set to False because it looks for the first found validation run
    is_published = False
    old_user = None
    max_vr_ind = len(vr_fields)
    max_run_ind = len(runs_set)
    run_ind = 0
    while not is_the_same and run_ind < max_run_ind:
        run = runs_set[run_ind]
        ind = 0
        while ind < max_vr_ind and getattr(run, vr_fields[ind]) == getattr(new_run, vr_fields[ind]):
            ind += 1
        if ind == max_vr_ind and _check_scaling_method(new_run, run):
            new_run_config = DatasetConfiguration.objects.filter(validation=new_run).order_by('dataset')
            old_run_config = DatasetConfiguration.objects.filter(validation=run).order_by('dataset')
            is_the_same = _compare_datasets(new_run_config, old_run_config)
            val_id = run.id
            is_published = run.doi != ''
            old_user = run.user
        run_ind += 1

    val_id = None if not is_the_same else val_id
    response = {
        'is_there_validation': is_the_same,
        'val_id': val_id,
        'belongs_to_user': old_user == user,
        'is_published': is_published
        }
    return response

__logger = logging.getLogger(__name__)

@login_required(login_url='/login/')
def stop_validation(request, result_uuid):
    if request.method == "DELETE":
        validation_run = get_object_or_404(ValidationRun, pk=result_uuid)
        if(validation_run.user != request.user):
            return HttpResponse(status=403)

        stop_running_validation(result_uuid)
        return HttpResponse("Validation stopped.", status=200)

    return HttpResponse(status=405) # if we're not DELETEing, send back "Method not Allowed"


@login_required(login_url='/login/')
def validation(request):
    dc_prefix = 'datasets'
    ref_prefix = 'ref'

    # some parameters to pass to template
    valrun_found = request.GET.get('valrun_found', None)
    valrun_uuid = request.GET.get("valrun_uuid", None)
    is_published = request.GET.get('is_published', None)
    belongs_to_user = request.GET.get('belongs', None)
    val_date = None

    # Get initial values for dataset forms
    def _default_initials():
        ref_initial_values = {
            "filters": DataFilter.objects.filter(
                name="FIL_ALL_VALID_RANGE"
            ),
            "dataset": Dataset.objects.get(short_name=val_globals.ISMN),
        }
        data_initial_values = [{
            "filters": DataFilter.objects.filter(
                name="FIL_ALL_VALID_RANGE"
            ),
            "dataset": Dataset.objects.get(short_name=val_globals.C3S),
        }]
        return ref_initial_values, data_initial_values

    # infer initial configuration values from POST request
    if request.method == "POST":
        def object_list_from_key(typ, key):
            return list(map(
                lambda x: typ.objects.get(pk=int(x)),
                request.POST.getlist(key)
            ))

        def object_from_key(typ, key):
            return typ.objects.get(pk=int(request.POST.get(key)[0]))

        try:
            prefixes = ["ref"]
            num_forms = int(request.POST.get("datasets-TOTAL_FORMS")[0])
            for i in range(num_forms):
                prefixes.append(f"datasets-{i}")

            initial_values = []
            for pfx in prefixes:
                initial_values.append({
                    "filters": object_list_from_key(
                        DataFilter, pfx + "-filters"
                    ),
                    "parametrised_filters": object_list_from_key(
                        DataFilter, pfx + "-parametrised_filters"
                    ),
                    "paramfilter_params": request.POST.getlist(
                        pfx + "-parametrised_filters_params"
                    ),
                    "dataset": object_from_key(
                        Dataset, pfx + "-dataset"
                    ),
                    "version": object_from_key(
                        DatasetVersion, pfx + "-version"
                    ),
                    "variable": object_from_key(
                        DataVariable, pfx + "-variable"
                    ),
                })
            ref_initial_values = initial_values[0]
            data_initial_values = initial_values[1:]

        except TypeError:
            # happens with invalid requests
            ref_initial_values, data_initial_values = _default_initials()

    # infer initial configuration values from GET request
    else:
        valrun_uuid = request.GET.get("valrun_uuid", None)
        if valrun_uuid is None:
            ref_initial_values, data_initial_values = _default_initials()
        else:
            valrun = get_object_or_404(ValidationRun, pk=valrun_uuid)
            # initial settings for datasets
            ref_config = valrun.reference_configuration
            data_configs = [dc for dc in valrun.dataset_configurations.all()
                            if dc.id != ref_config.id]
            initial_values = []
            for dc in [ref_config] + data_configs:
                initial_values.append({
                    "filters": dc.filters.all(),
                    "parametrised_filters": dc.parametrised_filters.all(),
                    "dataset": dc.dataset,
                    "version": dc.version,
                    "variable": dc.variable,
                })
                if initial_values[-1]["parametrised_filters"]:
                    paramfilter_params = dc.parametrisedfilter_set.all()
                    initial_values[-1].update({
                        "paramfilter_params": [
                            paramfilter_params.get(filter=filter_name).parameters
                            for filter_name in initial_values[-1]['parametrised_filters']
                        ]
                    })

            ref_initial_values = initial_values[0]
            data_initial_values = initial_values[1:]

    # get initial values for the validation run settings
    valrun_initial_values = {}
    for field in ValidationRunForm.Meta.fields:
        if request.method != "POST" and valrun_uuid is None:
            valrun_initial_values = None
        else:
            if request.method == "POST":
                valrun_initial_values[field] = request.POST.get(field)
            else:
                valrun_initial_values[field] = getattr(valrun, field)
            # the dates should be without time
            if isinstance(valrun_initial_values[field], datetime):
                valrun_initial_values[field] = (
                    valrun_initial_values[field].strftime("%Y-%m-%d")
                )
            if field.startswith("anomalies_") and isinstance(valrun_initial_values[field], str):
                # the fields anomalies_from and anomalies_to take an integer
                # year instead of a string datetime
                valrun_initial_values[field] = int(
                    valrun_initial_values[field][0:4]
                )

    if request.method == "POST":
        if Settings.load().maintenance_mode:
            __logger.info('Redirecting to the validation page because the system is in maintenance mode.')
            return redirect('validation')

        # formset for data configurations for our new validation
        dc_formset = DatasetConfigurationFormSet(request.POST, prefix=dc_prefix, initial=data_initial_values)

        ## apparently, a missing management form on the formset is a reason to throw a hissy fit err...
        ## ValidationError - instead of just appending it to dc_formset.non_form_errors. Whatever...
        try:
            dc_formset.is_valid()
        except ValidationError as e:
            __logger.exception(e)
            if e.code == 'missing_management_form':
                return HttpResponseBadRequest('Not a valid request: ' + e.message)

        # form for the reference configuration
        ref_dc_form = DatasetConfigurationForm(request.POST, prefix=ref_prefix, is_reference=True, initial=ref_initial_values)
        # form for the rest of the validation parameters
        val_form = ValidationRunForm(request.POST, initial=valrun_initial_values)
        if val_form.is_valid() and dc_formset.is_valid() and ref_dc_form.is_valid():
            newrun = val_form.save(commit=False)
            newrun.user = request.user
            newrun.start_time = datetime.now(tzlocal())

            if newrun.interval_from is not None:
                # truncate time
                newrun.interval_from = datetime(year=newrun.interval_from.year,
                                                month=newrun.interval_from.month,
                                                day=newrun.interval_from.day,
                                                tzinfo=newrun.interval_from.tzinfo)
            if newrun.interval_to is not None:
                # truncate time and go to 1 sec before midnight
                newrun.interval_to = datetime(year=newrun.interval_to.year,
                                                month=newrun.interval_to.month,
                                                day=newrun.interval_to.day,
                                                hour=23,
                                                minute=59,
                                                second=59,
                                                microsecond=999999,
                                                tzinfo=newrun.interval_to.tzinfo)
            newrun.save() # save the validation run
            run_id = newrun.id

            # attach all dataset configurations to the validation and save them
            for dc_form in dc_formset:
                dc = dc_form.save(commit=False)
                dc.validation = newrun
                dc.save()
                dc_form.save_m2m() # save many-to-many related objects, e.g. filters. If you don't do this, filters won't get saved!

            # also attach the reference config
            ref_dc = ref_dc_form.save(commit=False)
            ref_dc.validation = newrun
            ref_dc.save()
            ref_dc_form.save_m2m() # save many-to-many related objects, e.g. filters. If you don't do this, filters won't get saved!

            newrun.reference_configuration = ref_dc

            ## determine the scaling reference. For intercomparison, only the reference makes sense. Otherwise let the user pick.
            if ((len(dc_formset) == 1) and
                (val_form.cleaned_data['scaling_ref'] == ValidationRun.SCALE_TO_DATA)):
                newrun.scaling_ref = dc
            else:
                newrun.scaling_ref = ref_dc

            newrun.save()

            # checking if there exist validations:
            # using here Case and Where so that the current user always go first (its value is 0
            # and for other users is 1)
            existing_runs = ValidationRun.objects.filter(progress=100).exclude(output_file='').\
                            order_by(Case(When(user=request.user, then=0), default=1), '-start_time')
            comparison_pub = _compare_validation_runs(newrun, existing_runs, request.user)
            if_run_exists = comparison_pub['is_there_validation']
            # checking how many times the validation button was clicked - in 'try' so that tests pass
            try:
                clicked_times = int(request.POST.get('click-counter'))
            except:
                clicked_times = 0

            if if_run_exists and clicked_times == 1:
                newrun.delete()
                comparison, is_published = (comparison_pub, comparison_pub['is_published'])
                val_id = comparison['val_id']
                belongs_to_user = comparison['belongs_to_user']
                validation_settings = reverse('validation') + \
                                      '?valrun_uuid=' + str(val_id) + \
                                      '&valrun_found=' + str(int(if_run_exists)) + \
                                      '&is_published=' + str(int(is_published)) + \
                                      '&belongs=' + str(int(belongs_to_user))
                return redirect(validation_settings)

            # checking how many times the validation button was clicked - in try so that tests pass
            # need to close all db connections before forking, see
            # https://stackoverflow.com/questions/8242837/django-multiprocessing-and-database-connections/10684672#10684672
            connections.close_all()

            p = Process(target=run_validation, kwargs={"validation_id": run_id})
            p.start()

            return redirect('result', result_uuid=run_id)
        else:
            __logger.error("Errors in validation form {}\n{}\n{}".format(val_form.errors, dc_formset.errors, ref_dc_form.errors))
    else:
        val_form = ValidationRunForm(initial=valrun_initial_values)
        dc_formset = DatasetConfigurationFormSet(prefix=dc_prefix, initial=data_initial_values)
        ref_dc_form = DatasetConfigurationForm(prefix=ref_prefix, is_reference=True, initial=ref_initial_values)
        # ref_dc_form.

        # if validation exists:
        if valrun_found is not None:
            val_date = ValidationRun.objects.get(id=valrun_uuid).start_time
            valrun_found = bool(int(valrun_found))
            is_published = bool(int(is_published))
            belongs_to_user = bool(int(belongs_to_user))

    return render(request, 'validator/validate.html',
                  {'val_form': val_form, 'dc_formset': dc_formset, 'ref_dc_form': ref_dc_form,
                   'maintenance_mode':Settings.load().maintenance_mode, 'if_run_exists': valrun_found,
                   'val_id': valrun_uuid, 'is_published': is_published, 'belongs_to_user': belongs_to_user,
                   'val_date': val_date})


## Ajax stuff required for validation view

## render string options as html
def __render_options(entity_list, initial):
    widgets = []
    for entity in entity_list:
        widget = {
            'value': entity.id,
            'label': entity.pretty_name,
            }
        widgets.append(widget)
    # reorder such that "initial" is at the front
    if initial != "":
        init_val = int(initial)
        try:
            init_idx = [w["value"] for w in widgets].index(init_val)
            widgets.insert(0, widgets.pop(init_idx))
        except ValueError:  # pragma: no cover
            pass

    content = loader.render_to_string('widgets/select_options.html', {'widgets': widgets})
    return content


# render filters as html checkboxes with descriptions
def __render_filters(filters, filter_widget_id, initial_filters):
    widget_name = regex_subs(r'^id_', '', filter_widget_id)
    filter_field = ModelMultipleChoiceField(
        widget=FilterCheckboxSelectMultiple, queryset=filters, required=False
    )

    # extracts the initial filters to be selected from the initial_filters
    # string, see DatasetConfigurationForm.__init__
    if filters and initial_filters:
        initial_filter_ids = list(map(int, initial_filters.split(',')))
    else:
        initial_filter_ids = None

    filter_html = filter_field.widget.render(
        name=widget_name,
        value=initial_filter_ids,
        attrs={'id': filter_widget_id})
    return filter_html


# render filters as html checkboxes with descriptions
def __render_parametrised_filters(
        filters, filter_widget_id, initial_filters, initial_params
):
    widget_name = regex_subs(r'^id_', '', filter_widget_id)
    filter_field = ParamFilterChoiceField(
        widget=ParamFilterSelectMultiple, queryset=filters, required=False
    )

    # extracts the initial filters and params to be selected from the
    # initial_filters string, see DatasetConfigurationForm.__init__
    if filters and initial_filters:
        initial_filter_ids = list(map(int, initial_filters.split(",")))
        initial_parameters = initial_params.split(";")
    else:
        initial_filter_ids = None
        initial_parameters = None

    filter_html = filter_field.widget.render(
        name=widget_name,
        value=initial_filter_ids,
        attrs={'id': filter_widget_id,
               'initial_params': initial_parameters})
    return filter_html


## returns the options for the variable and version select dropdowns and the
## filter checkboxes based on the selected dataset
@login_required(login_url='/login/')
def ajax_get_dataset_options(request):
    selected_dataset_name = request.GET.get('dataset_id')
    filter_widget_id = request.GET.get('filter_widget_id')
    param_filter_widget_id = request.GET.get('param_filter_widget_id')
    initial_filters = request.GET.get('initial_filters')
    initial_paramfilters = request.GET.get('initial_paramfilters')
    initial_paramfilter_params = request.GET.get('initial_paramfilter_params')
    initial_version = request.GET.get('initial_version')
    initial_variable = request.GET.get('initial_variable')

    try:
        selected_dataset = Dataset.objects.get(pk=selected_dataset_name)
    except:
        return HttpResponseBadRequest("Not a valid dataset")

    response_data = {
        'versions': __render_options(
            selected_dataset.versions.all().order_by('-pretty_name'),
            initial_version,
        ),
        'variables': __render_options(
            selected_dataset.variables.all().order_by('id'),
            initial_variable
        ),
        'filters': __render_filters(
            selected_dataset.filters.filter(parameterised=False),
            filter_widget_id,
            initial_filters,
        ),
        'paramfilters': __render_parametrised_filters(
            selected_dataset.filters.filter(parameterised=True),
            param_filter_widget_id,
            initial_paramfilters,
            initial_paramfilter_params,
        ),
        }

    return JsonResponse(response_data)

@login_required(login_url='/login/')
def ajax_get_version_id(request):
    version_id = request.GET.get('version_id')
    try:
        version = DatasetVersion.objects.get(pk=int(version_id))
        networks = version.network_version.all()
        continents = networks.values('continent').distinct().values_list('continent', flat=True)
        network_dict =  {continent: [(network.name, network.country, network.number_of_stations) for network in networks.filter(continent=continent)] for continent in continents}
    except:
        return HttpResponseBadRequest("Not a valid dataset version")

    response_data = {
        'network': network_dict
        }

    return JsonResponse(response_data)

login_required(login_url='/login/')
def ajax_get_version_info(request):
    version_ids = request.GET.getlist('version_id')
    try:
        version_ids_int = [int(vid) for vid in version_ids]
        versions = DatasetVersion.objects.filter(pk__in=version_ids_int)
    except:
        return HttpResponseBadRequest("Not a valid dataset version")
    intervals_from = []
    intervals_to = []
    for version in versions:
        if 'ISMN' in version.short_name:
            time_from = val_globals.START_TIME
            time_to = val_globals.END_TIME
        else:
            time_from = version.time_range_start
            time_to = version.time_range_end
        intervals_from.append(time_from)
        intervals_to.append(time_to)

    response_data = {
        'intervals_from': intervals_from,
        'intervals_to' : intervals_to
        }
    return JsonResponse(response_data)
