FROM apache/airflow:2.8.1-python3.11

USER root
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-ind
COPY requirements.txt /
USER airflow

RUN pip install --no-cache-dir -r /requirements.txt

RUN cd /opt/airflow/weather_analytics && dbt deps || true
