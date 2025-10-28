import io
from PIL import Image
from celery import Celery
from common import celeryconfig, routing
from inside_return_featuremap import get_normalized_outputs
import base64

celery_app = Celery("inside")
celery_app.config_from_object(celeryconfig)
celery_app.conf.update(
    task_queues=routing.task_queues,
    task_default_exchange=routing.task_default_exchange,
    task_default_exchange_type=routing.task_default_exchange_type,
    task_default_routing_key=routing.task_default_routing_key,
)

@celery_app.task(name="inside.return_featuremap", bind=True, time_limit=120)
def return_featuremap(self, num_image_b64_str: str):
    contents = base64.b64decode(num_image_b64_str)
    pil_img = Image.open(io.BytesIO(contents))
    result = get_normalized_outputs(pil_img)
    return result
