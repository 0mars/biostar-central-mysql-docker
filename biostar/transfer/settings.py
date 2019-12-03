from conf.examples.pg.forum_settings import *

import os
TRANSFER_APP = ['biostar.transfer']

INSTALLED_APPS = DEFAULT_APPS + FORUM_APPS + ACCOUNTS_APPS + EMAILER_APP + TRANSFER_APP

DEBUG = True

WSGI_APPLICATION = 'conf.examples.postgres.postgres_wsgi.application'

TRANSFER_DATABASE = os.environ.setdefault("OLD_DATABASE", "old_biostar_db")

DATABASE_NAME = os.environ.setdefault("NEW_DATABASE", "new_biostar_db")

print(f'DATABASE_NAME={DATABASE_NAME}, TRANSFER_NAME={TRANSFER_DATABASE}')

DATABASES = {

    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': DATABASE_NAME,
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    },

    'biostar2': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': TRANSFER_DATABASE,
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
        'TEST': {
            'MIRROR': 'default',
        }
    },
}

try:
    from .postgres_secrets import *
except ImportError as exc:
    print("No postgres_secrets module could be imported")
