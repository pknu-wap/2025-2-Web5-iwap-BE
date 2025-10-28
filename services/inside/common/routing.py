from kombu import Exchange, Queue

exchange = Exchange("model_tasks", type="topic")

task_queues = (
    Queue("inside.q", exchange=exchange, routing_key="inside.*"),
    Queue("piano.q", exchange=exchange, routing_key="piano.*"),
)

task_default_exchange = "model_tasks"
task_default_exchange_type = "topic"
task_default_routing_key = "generic.task"
