import os
import sys
import logging
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def setup_database() -> None:
    if not DB_URL:
        log.error("DATABASE_URL tidak ditemukan di environment.")
        sys.exit(1)

    log.info("Menghubungkan ke Neon.tech...")
    try:
        with psycopg2.connect(DB_URL) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                log.info("Mengaktifkan ekstensi pgvector...")
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

                log.info("Membuat tabel documents...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id           SERIAL PRIMARY KEY,
                        source_url   TEXT        NOT NULL,
                        title        TEXT        NOT NULL,
                        content      TEXT        NOT NULL,
                        content_hash CHAR(64)    NOT NULL,
                        metadata     JSONB,
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unique_documents_source UNIQUE (source_url)
                    );
                """)

                log.info("Membuat tabel embeddings...")
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS embeddings (
                        id           SERIAL PRIMARY KEY,
                        document_id  INTEGER     NOT NULL
                                     REFERENCES documents(id) ON DELETE CASCADE,
                        chunk_index  INTEGER     NOT NULL,
                        chunk_text   TEXT        NOT NULL,
                        content_hash CHAR(64)    NOT NULL,
                        embedding    vector({EMBEDDING_DIM}) NOT NULL,
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unique_embedding_chunk
                            UNIQUE (document_id, chunk_index)
                    );
                """)

                log.info("Membuat HNSW index...")
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
                    ON embeddings USING hnsw (embedding vector_cosine_ops);
                """)

                log.info("Membuat tabel raw_weather...")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS raw_weather (
                        id                SERIAL PRIMARY KEY,
                        city_name         VARCHAR(100) NOT NULL,
                        observation_date  DATE         NOT NULL,
                        temperature_max   FLOAT,
                        precipitation_sum FLOAT,
                        wind_speed_max    FLOAT,
                        data_source       VARCHAR(20)  NOT NULL
                                          CHECK (data_source IN ('archive','forecast')),
                        ingested_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT unique_city_observation
                            UNIQUE (city_name, observation_date)
                    );
                """)

                log.info("Membuat index raw_weather...")
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_weather_city_date
                    ON raw_weather (city_name, observation_date);
                """)

                log.info("SUKSES! Database siap digunakan dari nol.")

    except psycopg2.Error as e:
        log.error(f"SETUP GAGAL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_database()
