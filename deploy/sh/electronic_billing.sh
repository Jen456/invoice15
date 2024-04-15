#!/bin/bash
DJANGO_DIR=$(dirname $(dirname $(cd `dirname $0` && pwd)))
DJANGO_SETTINGS_MODULE=config.settings
DJANGO_WSGI_MODULE=config.wsgi
cd $DJANGO_DIR
source venv/bin/activate
export DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
export PYTHONPATH=$DJANGO_DIR:$PYTHONPATH
exec python manage.py electronic_billing
