FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
  pandas==2.2.2 \
  numpy==2.0.1 \
  psycopg2-binary==2.9.9

COPY drift_detector.py /app/drift_detector.py

CMD ["python", "-u", "/app/drift_detector.py"]
