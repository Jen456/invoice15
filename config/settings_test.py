"""Ajustes para las pruebas automáticas (pytest).

Usa SQLite en memoria salvo que FPA_TEST_DATABASE_URL apunte a PostgreSQL
(obligatorio para las pruebas de concurrencia y aislamiento por filas).
"""
import os
import tempfile

os.environ['FPA_ENV_FILE'] = os.devnull
os.environ['SECRET_KEY'] = 'pruebas-automaticas-sin-valor-secreto'
os.environ['DEBUG'] = 'False'
os.environ['FPA_ENTORNO'] = 'pruebas_automaticas'
os.environ['DATABASE_URL'] = os.environ.get('FPA_TEST_DATABASE_URL', 'sqlite://:memory:')
os.environ['FPA_ARCHIVOS'] = tempfile.mkdtemp(prefix='fpa-archivos-')
os.environ['FPA_FIRMAS'] = tempfile.mkdtemp(prefix='fpa-firmas-')
os.environ.pop('FPA_LOGS', None)
os.environ.pop('FPA_X_ACCEL_PREFIX', None)

from config.settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ['testserver']
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
