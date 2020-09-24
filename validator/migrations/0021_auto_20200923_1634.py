# Generated by Django 3.1.1 on 2020-09-23 16:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('validator', '0020_auto_20200902_0756'),
    ]

    operations = [
        migrations.AddField(
            model_name='validationrun',
            name='tcol',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='user',
            name='first_name',
            field=models.CharField(blank=True, max_length=150, verbose_name='first name'),
        ),
    ]