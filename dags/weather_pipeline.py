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

    # TASK 1: setup database
    task_setup_db = BashOperator(
        task_id='setup_database',
        bash_command='cd /opt/airflow && python -m src.setup_db',
    )

    # Task 2: Ingest cuaca
    task_ingest = BashOperator(
        task_id='ingest_weather_data',
        bash_command='cd /opt/airflow && python -m src.ingest_weather',
    )

    # Task 3: Transformasi cuaca (dbt run)
    task_dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command='cd /opt/airflow/weather_analytics && dbt run',
    )

    # Task 4: Testing cuaca (dbt test)
    task_dbt_test = BashOperator(
        task_id='dbt_test',
        bash_command='cd /opt/airflow/weather_analytics && dbt test',
    )

    # Task 5: Embedding dokumen (RAG)
    task_embed = BashOperator(
        task_id='embed_documents',
        bash_command='cd /opt/airflow && python -m src.process_docs',
    )

    # setup DB -> Ingest -> (dbt_run & embed secara paralel) -> dbt_test
    task_setup_db >> task_ingest >> [task_dbt_run, task_embed]
    task_dbt_run >> task_dbt_test
