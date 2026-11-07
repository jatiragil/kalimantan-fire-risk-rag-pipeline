FROM apache/airflow:2.8.1-python3.11

# Pindah ke root untuk install sistem operasi
USER root

# Kembali ke user airflow
USER airflow

# Copy requirements.txt dan install
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt
