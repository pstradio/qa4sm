# Generated by Django 2.2.8 on 2020-05-15 16:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('validator', '0014b_validationrun_doi'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='orcid',
            field=models.CharField(blank=True, max_length=25),
        ),
    ]
