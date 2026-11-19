"""WSGI config for payplan project."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payplan.settings.prod")

application = get_wsgi_application()
