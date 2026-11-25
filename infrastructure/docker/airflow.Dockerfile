# Airflow 3 image with the project's dependencies (optional "orchestration" compose profile).
FROM apache/airflow:3.1.5-python3.12
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
