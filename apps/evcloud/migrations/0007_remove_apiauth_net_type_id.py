# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-12-29 12:54
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('evcloud', '0006_auto_20181205_2236'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='apiauth',
            name='net_type_id',
        ),
    ]