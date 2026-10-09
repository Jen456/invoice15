"""
Configuración de FacturaPorAquí.

Los valores que dependen del entorno o son secretos se leen de variables de
entorno. En los servidores las define el EnvironmentFile de systemd
(/etc/facturaporaqui/<entorno>.env); en desarrollo se puede usar un archivo
.env en la raíz del proyecto o indicar otro con FPA_ENV_FILE (ver .env.ejemplo).
"""
import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
_env_file = os.environ.get('FPA_ENV_FILE', str(BASE_DIR / '.env'))
if os.path.isfile(_env_file):
    environ.Env.read_env(_env_file)

FPA_ENTORNO = env('FPA_ENTORNO', default='desarrollo')

SECRET_KEY = env('SECRET_KEY')

DEBUG = env.bool('DEBUG', default=False)

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'] if DEBUG else [])

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'widget_tweaks',
    'django_user_agents',
    'django_cleanup.apps.CleanupConfig',
]

LOCAL_APPS = [
    'core.security',
    'core.user',
    'core.login',
    'core.dashboard',
    'core.pos',
    'core.reports',
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS + THIRD_PARTY_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'crum.CurrentRequestUserMiddleware',
    'django_user_agents.middleware.UserAgentMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.security.context_processors.site_settings',
                'core.security.context_processors.session_profile',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Base de datos: PostgreSQL en los servidores; SQLite solo como respaldo local.
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
}
DATABASES['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=60)
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default'].setdefault('OPTIONS', {}).setdefault('connect_timeout', 5)

# Caché en base de datos: compartida entre procesos de Gunicorn (límite de
# intentos de inicio de sesión). Tabla creada con `manage.py createcachetable`.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'fpa_cache',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ec'

TIME_ZONE = 'America/Guayaquil'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'

STATICFILES_DIRS = [BASE_DIR / 'static']

STATIC_ROOT = env('STATIC_ROOT', default=str(BASE_DIR / 'staticfiles'))

# Archivos subidos: fuera de public_html y sin acceso para nginx. Se entregan
# solo a usuarios autenticados a través de core.security.views.files.
MEDIA_ROOT = env('FPA_ARCHIVOS', default=str(BASE_DIR / 'media'))

MEDIA_URL = '/media/'

# Opcional: prefijo de una ubicación `internal` de nginx para X-Accel-Redirect.
# Vacío = Django entrega el archivo (los servidores lo usan así: nginx no lee los datos).
FPA_X_ACCEL_PREFIX = env('FPA_X_ACCEL_PREFIX', default='')

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

FILE_UPLOAD_PERMISSIONS = 0o640

FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o2750

# Ruta del admin de Django (solo superusuarios); en los servidores no es la predeterminada.
FPA_ADMIN_URL = env('FPA_ADMIN_URL', default='admin/')

LOGIN_REDIRECT_URL = '/dashboard/'

LOGOUT_REDIRECT_URL = '/login/'

LOGIN_URL = '/login/'

AUTH_USER_MODEL = 'user.User'

# Límite de intentos fallidos de inicio de sesión por IP y usuario.
FPA_LOGIN_MAX_INTENTOS = env.int('FPA_LOGIN_MAX_INTENTOS', default=5)

FPA_LOGIN_BLOQUEO_SEGUNDOS = env.int('FPA_LOGIN_BLOQUEO_SEGUNDOS', default=900)

# Correo de la plataforma (notificaciones y recuperación de contraseña).
EMAIL_HOST = env('EMAIL_HOST', default='localhost')

EMAIL_PORT = env.int('EMAIL_PORT', default=587)

EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)

EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')

EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')

EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=20)

DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER or 'webmaster@localhost')

# Sesiones y cookies. El JavaScript existente lee la cookie csrftoken, por eso
# CSRF_COOKIE_HTTPONLY queda en False.
SESSION_COOKIE_NAME = 'fpa_sesion'

SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)

CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)

SESSION_COOKIE_AGE = env.int('SESSION_COOKIE_AGE', default=8 * 3600)

# Detrás de nginx (que fija X-Forwarded-Proto) y de Cloudflare.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)

SECURE_HSTS_INCLUDE_SUBDOMAINS = False

SECURE_CONTENT_TYPE_NOSNIFF = True

# PayPhone valida el dominio de origen: hace falta enviar el origen en
# peticiones a otros sitios (strict-origin-when-cross-origin lo hace en HTTPS).
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'

X_FRAME_OPTIONS = 'DENY'

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

GROUPS = {
    'client': 2
}

# Registros: a la consola (journald) y, si se define FPA_LOGS, a un archivo
# rotado por logrotate. Nunca se registran contraseñas, tokens ni claves.
FPA_LOGS = env('FPA_LOGS', default='')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{asctime} {levelname} {name} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', default='INFO')},
    'loggers': {
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'weasyprint': {'level': 'WARNING'},
        'fontTools': {'level': 'WARNING'},
    },
}

if FPA_LOGS:
    LOGGING['handlers']['archivo'] = {
        'class': 'logging.handlers.WatchedFileHandler',
        'filename': os.path.join(FPA_LOGS, 'app.log'),
        'formatter': 'simple',
    }
    LOGGING['root']['handlers'].append('archivo')
    LOGGING['loggers']['django.security']['handlers'].append('archivo')
