import logging
import os
from datetime import timedelta

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "contentapi.settings")


app = Celery("contentapi")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.beat_schedule = {
    "task1": {
        "task": "contents.tasks.pull_and_store_content",
        "schedule": timedelta(seconds=5),
    },
    "task2": {
        "task": "contents.tasks.generate_comment",
        "schedule": timedelta(seconds=5),
    },
    "task2": {
        "task": "contents.tasks.post_comment",
        "schedule": timedelta(seconds=30),
    },
}

app.autodiscover_tasks()
