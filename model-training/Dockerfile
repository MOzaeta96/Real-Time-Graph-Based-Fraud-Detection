FROM python:3.11-slim
WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends libgomp1 \
  && rm -rf /var/lib/apt/lists/*

COPY model-training/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common_fraud /app/common_fraud
COPY model-training/train_lgbm.py /app/train_lgbm.py

ENV PYTHONPATH=/app
CMD ["python", "/app/train_lgbm.py"]