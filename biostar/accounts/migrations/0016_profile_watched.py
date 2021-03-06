# Generated by Django 3.1 on 2020-11-24 17:29

from django.db import migrations
import taggit.managers


class Migration(migrations.Migration):
    dependencies = [
        ('taggit', '0003_taggeditem_add_unique_index'),
        ('accounts', '0015_profile_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='watched',
            field=taggit.managers.TaggableManager(help_text='A comma-separated list of tags.',
                                                  through='taggit.TaggedItem', to='taggit.Tag', verbose_name='Tags'),
        ),
    ]
