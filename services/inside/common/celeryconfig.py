import os

broker_url = os.environ.get("BROKER_URL", "amqp://guest:guest@rabbitmq:5672//")
result_backend = os.environ.get("RESULT_BACKEND", "redis://redis:6379/0")

task_time_limit = 120
task_soft_time_limit = 110
worker_prefetch_multiplier = 4
task_acks_late = True
worker_concurrency = 2
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "Asia/Seoul"
enable_utc = True
