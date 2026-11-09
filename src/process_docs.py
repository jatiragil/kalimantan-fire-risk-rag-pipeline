import os
import sys
import json
import time
import re
import logging
import hashlib
import psycopg2
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Setup Environment
load_dotenv()

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Inisialisasi Client Gemini
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    log.error("GEMINI_API_KEY tidak ditemukan di .env")
    sys.exit(1)

def chunk_text(text: str, max_chars: int = 600, overlap: int = 100) -> list:
    """Memotong teks berdasarkan paragraf (paragraph-aware chunking)."""
    paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
    chunks = []
    current_chunk = ""
    
    for p in paragraphs:
        if len(current_chunk) + len(p) <= max_chars:
            current_chunk += p + "\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = (current_chunk[-overlap:] + " " + p + "\n") if current_chunk else (p + "\n")
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def get_embedding(text: str):
    """Memanggil Google Gemini API untuk mengubah teks menjadi vektor 768 dimensi."""
    try:
        # Menggunakan config untuk menentukan dimensi output dan tipe task
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=768
            )
        )
        
        embedding = response.embeddings[0].values
        
        if not isinstance(embedding, list):
            log.error(f"Format respons API salah: {embedding}")
            return None
            
        time.sleep(0.5) # Pacing
        return embedding
        
    except Exception as e:
        log.error(f"Gemini API Error: {e}")
        return None

def process_documents():
    filepath = "data/bmkg_snapshot.json"
    
    if not os.path.exists(filepath):
        log.error(f"File {filepath} tidak ditemukan.")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        articles = json.load(f)

    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        for article in articles:
            url = article["url"]
            title = article["title"]
            content = article["content"]
            
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

            # Idempotency Check
            cur.execute("SELECT id, content_hash FROM documents WHERE source_url = %s", (url,))
            doc_row = cur.fetchone()

            if doc_row and doc_row[1] == content_hash:
                log.info(f"Skip (Tidak ada perubahan): {title}")
                continue

            if doc_row:
                doc_id = doc_row[0]
                log.info(f"Update Dokumen: {title}")
                cur.execute("""
                    UPDATE documents SET title=%s, content=%s, content_hash=%s, updated_at=NOW() WHERE id=%s
                """, (title, content, content_hash, doc_id))
                cur.execute("DELETE FROM embeddings WHERE document_id=%s", (doc_id,))
            else:
                log.info(f"Insert Dokumen Baru: {title}")
                cur.execute("""
                    INSERT INTO documents (source_url, title, content, content_hash) 
                    VALUES (%s, %s, %s, %s) RETURNING id
                """, (url, title, content, content_hash))
                doc_id = cur.fetchone()[0]

            chunks = chunk_text(content)
            log.info(f"Memotong menjadi {len(chunks)} chunk. Mulai Embedding...")
            
            success_count = 0
            
            for i, chunk in enumerate(chunks):
                log.info(f"  -> Memproses Chunk {i+1}/{len(chunks)}...")
                vector = get_embedding(chunk)
                
                if not vector:
                    log.warning(f"Gagal embed chunk {i+1}, dilewati.")
                    continue
                
                chunk_hash = hashlib.sha256(chunk.encode('utf-8')).hexdigest()
                cur.execute("""
                    INSERT INTO embeddings (document_id, chunk_index, chunk_text, content_hash, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                """, (doc_id, i, chunk, chunk_hash, vector))
                success_count += 1

            # Fail-Fast
            if success_count == 0:
                conn.rollback() 
                log.error(f"GAGAL TOTAL: 0 Chunk berhasil di-embed untuk '{title}'. Rollback!")
                continue
            
            conn.commit()
            log.info(f"Selesai memproses dokumen: {title}\n")

        cur.close()
        conn.close()
        log.info("SELURUH DOKUMEN BERHASIL DIPROSES!")

    except Exception as e:
        log.error(f"Proses dibatalkan karena error tak terduga: {e}")
        if conn:
            conn.rollback()
        sys.exit(1)

if __name__ == "__main__":
    if not DB_URL or not GEMINI_API_KEY:
        log.error("Pastikan DATABASE_URL dan GEMINI_API_KEY ada di .env")
        sys.exit(1)
    process_documents()