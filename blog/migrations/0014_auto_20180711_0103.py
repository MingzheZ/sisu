# Generated by Django 2.0.5 on 2018-07-11 00:03

import blog.models
from django.db import migrations
import enumfields.fields


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0013_auto_20180711_0049'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='category_name',
            field=enumfields.fields.EnumField(default='A', enum=blog.models.Category, max_length=30),
        ),
    ]