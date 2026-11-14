from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'jati',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

with DAG(
    dag_id='weather_karhutla_pipeline',
    default_args=default_args,
    description='Dual-Pipeline: Weather Data & Karhutla RAG Documents',
    schedule='0 1 * * *',
    start_date=datetime(2026, 11, 1),
    catchup=False,
) as dag:

    # TASK 1: Setup Database (Single Source of Truth)
    task_setup_db = BashOperator(
        task_id='setup_database',
        bash_command='cd /opt/airflow && python -m src.setup_db',
    )

    # TASK 2: Ingest Cuaca (Open-Meteo)
    task_ingest_weather = BashOperator(
        task_id='ingest_weather_data',
        bash_command='cd /opt/airflow && python -m src.ingest_weather',
    )

    # TASK 3: Transformasi Cuaca (dbt run)
    task_dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command='cd /opt/airflow/weather_analytics && dbt run --profiles-dir .',
    )

    # TASK 4: Testing Cuaca (dbt test)
    task_dbt_test = BashOperator(
        task_id='dbt_test',
        bash_command='cd /opt/airflow/weather_analytics && dbt test --profiles-dir .',
    )

    # TASK 5: Ingestion Dokumen (PDF, OCR, Embedding)
    task_ingest_docs = BashOperator(
        task_id='ingest_documents',
        bash_command='cd /opt/airflow && python -m src.ingest_documents',
        execution_timeout=timedelta(minutes=30), # Beri waktu 30 menit untuk OCR
    )

    # ALUR DEPENDENSI
    # 1. Setup DB selesai -> Ingest Cuaca
    # 2. Ingest Cuaca selesai -> Jalan paralel: (dbt_run) DAN (ingest_documents)
    # 3. dbt_run selesai -> dbt_test
    task_setup_db >> task_ingest_weather >> [task_dbt_run, task_ingest_docs]
    task_dbt_run >> task_dbt_test
