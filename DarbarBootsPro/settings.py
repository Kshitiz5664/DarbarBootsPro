from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-secret-key")

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Your apps
    'UserAuth',
    'core',
    'items',
    'party',
    'billing',
    'wholesale',
    'retailapp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',

    # Enable WhiteNoise
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'DarbarBootsPro.urls'
WSGI_APPLICATION = 'DarbarBootsPro.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ------------------------------------------------------------
# ✅ DATABASE CONFIG — Railway (PostgreSQL) + LOCAL (SQLite)
# ------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Production (Railway cloud PostgreSQL)
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=False
        )
    }
else:
    # Local development (SQLite)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ------------------------------------------------------------
# STATIC & MEDIA FILES
# ------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ------------------------------------------------------------
# SECURITY
# ------------------------------------------------------------
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

PORT = os.getenv("PORT", "8000")
