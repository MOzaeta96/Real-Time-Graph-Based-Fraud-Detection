FROM python:3.11-slim
WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY retrain-controller/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common_fraud /app/common_fraud
COPY retrain-controller/retrain_controller.py /app/retrain_controller.py

ENV PYTHONPATH=/app
CMD ["python", "/app/retrain_controller.py"]