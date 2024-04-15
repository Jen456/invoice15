#!/bin/bash

# Define variables
DJANGO_DIR=$(dirname $(dirname $(cd `dirname $0` && pwd)))
VENV_DIR="$DJANGO_DIR/venv"
DB_DIR="$DJANGO_DIR/db.sqlite3"
MEDIA_DIR="$DJANGO_DIR/media"
DJANGO_SETTINGS_MODULE="config.settings"

# Change to the Django project directory
cd "$DJANGO_DIR" || exit

echo 'Deleting database and media folder'
# Check and delete the database if it exists
if [ -f "$DB_DIR" ]; then
  rm "$DB_DIR"
fi

# Check and delete the media folder if it exists
if [ -d "$MEDIA_DIR" ]; then
  rm -r "$MEDIA_DIR"
fi

echo 'Activating virtual environment and installing requirements'
# Activate the virtual environment
source "$VENV_DIR/bin/activate"
export DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE"

# Install requirements
pip install -r "$DJANGO_DIR/deploy/txt/requirements.txt"

echo 'Creating the database and inserting test data'
# Remove existing migrations (except __init__.py) and migrate the database
find . -path "*/migrations/*.py" -not -name "__init__.py" ! -path "*/venv/*" -delete
python manage.py makemigrations && python manage.py migrate && python manage.py start_installation && python manage.py insert_test_data

echo 'Process finished'
