"""
Django settings for webserver project.

Generated by 'django-admin startproject' using Django 1.11.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""

import os
import sys
import datetime

# import raven

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(BASE_DIR, 'apps'))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = ['*',]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 第三方apps
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_swagger',
    'ckeditor',
    # 'ckeditor_uploader',
    # 'raven.contrib.django.raven_compat',

    #自定义apps
    'buckets.apps.BucketsConfig',
    'users.apps.UsersConfig',
    'api',
    'evcloud',
    'docs',
    'vpn',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'webserver.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'webserver.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'collect_static')
#静态文件查找路径
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

#上传文件
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, "media") 

#session 有效期设置
SESSION_SAVE_EVERY_REQUEST = True #
SESSION_EXPIRE_AT_BROWSER_CLOSE = True #True：关闭浏览器，则Cookie失效。
# SESSION_COOKIE_AGE=60*30   #30分钟

#自定义用户模型
AUTH_USER_MODEL = 'users.UserProfile'

# 避免django把未以/结尾的url重定向到以/结尾的url
APPEND_SLASH=False

#登陆url
LOGIN_URL = '/users/login/'
LOGOUT_URL = '/users/logout/'

# api docs
SWAGGER_SETTINGS = {
    # 'SECURITY_DEFINITIONS': {
    #     'basic': {
    #         'type': 'basic'
    #     }
    # },
    # 'SHOW_REQUEST_HEADERS': True,
    # 'JSON_EDITOR': True,
    'DOC_EXPANSION': 'list',
}


REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': [
        # 'rest_framework.permissions.IsAuthenticatedOrReadOnly',
        'rest_framework.permissions.IsAuthenticated',
        # 'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework_jwt.authentication.JSONWebTokenAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    # 'DEFAULT_THROTTLE_CLASSES': (
    #     'rest_framework.throttling.AnonRateThrottle',  # 未登陆认证的用户默认访问限制
    #     'rest_framework.throttling.UserRateThrottle'  # 登陆认证的用户默认访问限制
    # ),
    # 'DEFAULT_THROTTLE_RATES': {
    #     'anon': '5/minute',  # 未登陆认证的用户默认请求访问限制每分钟次数
    #     'user': '20/minute'  # 登陆认证的用户默认请求访问限制每分钟次数
    # },
    # api version settings
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ('v1', ),
    'VERSION_PARAM': 'version',

    # 分页
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100
}

JWT_AUTH = {
    'JWT_EXPIRATION_DELTA': datetime.timedelta(days=1),
    'JWT_ALLOW_REFRESH': True,
    'JWT_REFRESH_EXPIRATION_DELTA': datetime.timedelta(days=7),
}

# Ceph rados settings
CEPH_RADOS = {
    'CLUSTER_NAME': 'ceph',
    'USER_NAME': 'client.admin',
    'CONF_FILE_PATH': '/etc/ceph/ceph.conf',
    'POOL_NAME': 'p0',
    'RADOS_DLL_PATH': 'rados.so'
}

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        # logging file settings
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'log/webserver.log'),
            'formatter': 'verbose'
        },
        # output to console settings
        'console': {
            'level': 'INFO',
            'filters': ['require_debug_true'],# working with debug mode
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        # 邮件通知
        # 'mail_admins': {
        #     'level': 'ERROR',
        #     'class': 'django.utils.log.AdminEmailHandler',
        #     'filters': ['special']
        # }
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['file', 'console'],#'mail_admins'
            'level': 'ERROR',
            'propagate': False,
        },
        # 'django.server': {
        #     'handlers': ['file', 'console'],
        #     'level': 'ERROR',
        #     'propagate': False,
        # },
    },
}

# ckeditor
# CKEDITOR_UPLOAD_PATH = "upload/"
CKEDITOR_CONFIGS = {
    'default': {
        'skin': 'moono',
        # 'skin': 'office2013',
        'toolbar_Basic': [
            ['Source', '-', 'Bold', 'Italic']
        ],
        'toolbar_YourCustomToolbarConfig': [
            {'name': 'document', 'items': ['Source', '-', 'Save', 'NewPage', 'Preview', 'Print', '-', 'Templates']},
            {'name': 'clipboard', 'items': ['Cut', 'Copy', 'Paste', 'PasteText', 'PasteFromWord', '-', 'Undo', 'Redo']},
            {'name': 'editing', 'items': ['Find', 'Replace', '-', 'SelectAll']},
            {'name': 'forms',
             'items': ['Form', 'Checkbox', 'Radio', 'TextField', 'Textarea', 'Select', 'Button', 'ImageButton',
                       'HiddenField']},
            '/',
            {'name': 'basicstyles',
             'items': ['Bold', 'Italic', 'Underline', 'Strike', 'Subscript', 'Superscript', '-', 'RemoveFormat']},
            {'name': 'paragraph',
             'items': ['NumberedList', 'BulletedList', '-', 'Outdent', 'Indent', '-', 'Blockquote', 'CreateDiv', '-',
                       'JustifyLeft', 'JustifyCenter', 'JustifyRight', 'JustifyBlock', '-', 'BidiLtr', 'BidiRtl',
                       'Language']},
            {'name': 'links', 'items': ['Link', 'Unlink', 'Anchor']},
            {'name': 'insert',
             'items': ['Image', 'Flash', 'Table', 'HorizontalRule', 'Smiley', 'SpecialChar', 'PageBreak', 'Iframe']},
            '/',
            {'name': 'styles', 'items': ['Styles', 'Format', 'Font', 'FontSize']},
            {'name': 'colors', 'items': ['TextColor', 'BGColor']},
            {'name': 'tools', 'items': ['Maximize', 'ShowBlocks']},
            {'name': 'about', 'items': ['About']},
            '/',  # put this to force next toolbar on new line
            {'name': 'yourcustomtools', 'items': [
                # put the name of your editor.ui.addButton here
                'Preview',
                'Maximize',
            ]},
        ],
        'toolbar': 'YourCustomToolbarConfig',  # put selected toolbar config here
        'tabSpaces': 4,
    },
    'custom': {
        'toolbar': 'Custom',
        'toolbar_Custom': [
            {'name': 'styles', 'items': ['Format', 'Bold', 'Italic', 'Underline']},
            {'name': 'paragraph',
             'items': ['NumberedList', 'Outdent', 'Indent', 'JustifyLeft',
                       'JustifyCenter', 'JustifyRight', 'JustifyBlock']},
            {'name': 'colors', 'items': ['TextColor', 'BGColor']},
            {'name': 'insert', 'items': ['Link', 'Unlink', 'Image', 'Smiley', 'SpecialChar']},
            {'name': 'tools',
             'items': ['RemoveFormat', 'Undo', 'Redo', 'SelectAll', 'Maximize', 'Source']},
        ],
        # 配置上传图片时不需要的内联样式属性
        'disallowedContent': 'img{width,height,margin-left, margin-right};img[width,height,margin-left, margin-right];'
    },
}


DATABASE_ROUTERS = [
    'webserver.db_routers.MetadataRouter',
]

# 导入安全相关的settings
from .security_settings import *

# The following is examples for security_settings.py

# SECURITY WARNING: keep the secret key used in production secret!
# SECRET_KEY = 'tbfpk*ax#48#^_qzr-cg07&z9&+8j68=x41w5lzv^wsv7xax=v'

# # Database
# # https://docs.djangoproject.com/en/1.11/ref/settings/#databases
#
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': 'db.sqlite3',
#     }
# }

#mongodb数据库连接
# from mongoengine import connect
#
# connect(
#     alias='default',
#     db='metadata',
#     host='10.0.86.213',
#     port=27017,
#     # username='***',
#     # password='***',
#     # authentication_source='admin'
# )
# connect(alias='db2', db='testdb2', host='10.0.86.213', port=27017)

# 邮箱配置
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_USE_TLS = True   #是否使用TLS安全传输协议
# # EMAIL_PORT = 25
# EMAIL_HOST = 'xxx'
# EMAIL_HOST_USER = 'xxx'
# EMAIL_HOST_PASSWORD = 'xxx'

# RAVEN_CONFIG = {
#     'dsn': 'sentry上面创建项目的时候得到的dsn'
# }


