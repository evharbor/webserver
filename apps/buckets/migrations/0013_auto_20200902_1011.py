# Generated by Django 2.2.14 on 2020-09-02 02:11

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0012_bucket_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='archive',
            name='type',
            field=models.SmallIntegerField(choices=[(0, '普通'), (1, 'S3')], default=0, verbose_name='桶类型'),
        ),
        migrations.AlterField(
            model_name='bucket',
            name='user',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='所属用户'),
        ),
    ]
