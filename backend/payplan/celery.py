import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "payplan.settings.dev")

app = Celery("payplan")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "due-reminders-daily": {
        "task": "payments.tasks.send_due_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    "scheduled-charges-daily": {
        "task": "payments.tasks.run_scheduled_charges",
        "schedule": crontab(hour=10, minute=0),
    },
    "dunning-daily": {
        "task": "payments.tasks.run_dunning",
        "schedule": crontab(hour=11, minute=0),
    },
    "nightly-rollup": {
        "task": "plans.tasks.nightly_rollup",
        "schedule": crontab(hour=2, minute=0),
    },
}
