FROM python:3.13-slim

WORKDIR /worker

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements.txt /worker/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY common /worker/common
COPY . /worker
ENV PYTHONPATH=/worker

CMD ["bash", "-lc", "celery -A tasks.celery_app worker -Q inside.q --loglevel=INFO"]