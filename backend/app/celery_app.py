from celery import Celery

from app.config import settings


celery_app = Celery("kifu_comment", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_always_eager=settings.analysis_eager,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-analysis-outbox": {
            "task": "app.tasks.dispatch_pending_analysis_jobs",
            "schedule": 30.0,
        }
    },
)
celery_app.autodiscover_tasks(["app"])
