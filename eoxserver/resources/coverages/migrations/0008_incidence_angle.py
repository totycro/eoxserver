# -*- coding: utf-8 -*-
# Generated by Django 2.2.9 on 2020-08-18 13:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('coverages', '0007_typemodels'),
    ]

    operations = [
        migrations.AddField(
            model_name='ProductMetadata',
            name='across_track_incidence_angle',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='ProductMetadata',
            name='along_track_incidence_angle',
            field=models.FloatField(blank=True, db_index=True, null=True),
        ),
    ]
