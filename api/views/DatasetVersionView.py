from django.http import JsonResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.serializers import ModelSerializer

from validator.models import DatasetVersion, Dataset


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dataset_version(request):
    dataset_id = request.query_params.get('dataset', None)
    # # get single dataset
    if dataset_id:
        versions = Dataset.objects.get(id=dataset_id).versions
    # get all datasets
    else:
        versions = DatasetVersion.objects.all()

    serializer = DatasetVersionSerializer(versions, many=True)

    return JsonResponse(serializer.data, status=status.HTTP_200_OK, safe=False)


class DatasetVersionSerializer(ModelSerializer):
    class Meta:
        model = DatasetVersion
        fields = ['id',
                  'short_name',
                  'pretty_name',
                  'help_text',
                  'time_range_start',
                  'time_range_end',
                  ]