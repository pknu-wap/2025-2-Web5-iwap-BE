import os
from celery import Celery

broker = os.environ.get("BROKER_URL", "amqp://guest:password123@rabbitmq:5672//")
backend = os.environ.get("RESULT_BACKEND", "redis://redis:6379/0")

celery = Celery("api", broker=broker, backend=backend)
celery.config_from_object("common.celeryconfig")
celery.conf.imports = []
