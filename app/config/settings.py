import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
# Authentication and its migrations are introduced in P2, with the custom user model.
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.staticfiles', 'core']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': ['django.template.context_processors.request']},
}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ['POSTGRES_DB'],
    'USER': os.environ['POSTGRES_USER'],
    'PASSWORD': os.environ['POSTGRES_PASSWORD'],
    'HOST': 'db', 'PORT': '5432',
    'OPTIONS': {'connect_timeout': 5},
}}
LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = Path('/media')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
