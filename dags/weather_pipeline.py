from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'jati',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

with DAG(
    dag_id='weather_karhutla_pipeline',
    default_args=default_args,
    description='Pipeline cuaca dan karhutla otomatis',
    schedule='0 1 * * *',
    start_date=datetime(2026, 11, 1),
    catchup=False,
) as dag:

    # Task 1: Ingest Cuaca
    task_ingest = BashOperator(
        task_id='ingest_weather_data',
        bash_command='cd /opt/airflow && python -m src.ingest_weather',
    )

    # Task 2: Transformasi Cuaca (dbt run)
    task_dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command='cd /opt/airflow/weather_analytics && dbt run',
    )

    # Task 3: Testing Cuaca (dbt test)
    task_dbt_test = BashOperator(
        task_id='dbt_test',
        bash_command='cd /opt/airflow/weather_analytics && dbt test',
    )

    # Task 4: Embedding Dokumen (RAG)
    task_embed = BashOperator(
        task_id='embed_documents',
        bash_command='cd /opt/airflow && python -m src.process_docs',
    )

    # TOPOLOGY
    task_ingest >> [task_dbt_run, task_embed]
    
    # Jalur dbt harus berurutan
    task_dbt_run >> task_dbt_test
