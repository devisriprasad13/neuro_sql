"""
Celery application instance.

This module is the entry point for Celery workers and Flower.
All async tasks are registered here.

Queues:
    default → general tasks
    query   → NL query execution tasks (can scale independently)
    schema  → schema crawl and embedding tasks
"""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "neurosql",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.query_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # How long to keep task results in Redis
    result_expires=3600,  # 1 hour
    # Task routing
    task_routes={
        "tasks.execute_query": {"queue": "query"},
        "tasks.crawl_schema":  {"queue": "schema"},
    },
)