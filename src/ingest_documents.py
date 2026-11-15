import os
import re
import sys
import time
import hashlib
import logging
import unicodedata
from pathlib import Path
import pymupdf
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    log.error("GEMINI_API_KEY tidak ditemukan.")
    sys.exit(1)

RAW_DIR = Path("data/raw_docs")

# ==========================================
# 1. PEMBERSIH & EKSTRAKTOR
# ==========================================
def clean_text(text: str) -> str:
    if not text: return ""
    # 1. Hapus tag <mark> dan </mark> dari OCR
    text = re.sub(r'</?mark>', '', text)
    # 2. Hapus karakter spasi aneh
    text = text.replace('\xa0', ' ').replace('\u200b', '')
    # 3. Normalisasi unicode
    text = unicodedata.normalize('NFKC', text)
    # 4. Bersihkan sampah OCR di awal baris (seperti ===, ---, |||)
    text = re.sub(r'^[\=\-\|\s]+', '', text, flags=re.MULTILINE)
    # 5. Rapatkan baris kosong berlebih
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return '\n'.join([line.strip() for line in text.split('\n')]).strip()

def extract_text_from_file(file_path: Path) -> str:
    # Abaikan file cache OCR
    if file_path.name.endswith('.ocr.txt'):
        return ""

    if file_path.suffix.lower() == '.pdf':
        cache_path = file_path.with_suffix('.ocr.txt')
        if cache_path.exists():
            log.info(f"  -> Menggunakan cache OCR: {cache_path.name}")
            return cache_path.read_text(encoding='utf-8')

        log.info(f"  -> OCR pada {file_path.name} (mohon tunggu, ini bisa memakan waktu)...")
        doc = pymupdf.open(file_path)
        full_text = doc.to_markdown()
        doc.close()
        
        cache_path.write_text(full_text, encoding='utf-8')
        return full_text
    
    elif file_path.suffix.lower() == '.txt':
        return file_path.read_text(encoding='utf-8')
    
    return ""

# ==========================================
# 2. METADATA DINAMIS (Trust but Verify)
# ==========================================
def infer_metadata(file_path: Path, raw_text: str) -> dict:
    filename_lower = file_path.name.lower()
    meta = {"doc_type": "umum", "doc_date": None}
    
    # Infer doc_type dari nama file
    if "sop" in filename_lower: meta["doc_type"] = "sop"
    elif "glosarium" in filename_lower: meta["doc_type"] = "glosarium"
    elif "spartan" in filename_lower: meta["doc_type"] = "spartan"
    
    # Infer doc_date (Regex 4 digit tahun)
    year_match = re.search(r'(20\d{2})', filename_lower)
    if year_match:
        meta["doc_date"] = f"{year_match.group(1)}-01-01"
    else:
        log.warning(f"  [!] Tidak ada tahun di nama file: {file_path.name}")
        
    # Validasi teks
    text_lower = raw_text[:1000].lower()
    if meta["doc_type"] == "sop" and "prosedur" not in text_lower and "sop" not in text_lower:
        log.warning(f"  [!] Peringatan: File '{file_path.name}' ditebak SOP, tapi teks tidak mengandung 'prosedur/SOP'.")
        
    return meta

# ==========================================
# 3. CHUNKER DINAMIS (Regex Markdown)
# ==========================================
def force_split_text(text: str, max_chars: int = 800) -> list[str]:
    """Pemotong paksa yang tidak bisa dibohongi oleh OCR."""
    if len(text) <= max_chars:
        return [text]
    
    sub_chunks = []
    # Coba split by double newline dulu (paragraf normal)
    paragraphs = re.split(r'\n\s*\n', text)
    
    # Kalau tidak ada double newline (OCR berantakan), split per single newline
    if len(paragraphs) == 1:
        paragraphs = text.split('\n')
        
    current_chunk = ""
    for p in paragraphs:
        p = p.strip()
        if not p: continue

        # Kalau satu baris/paragraf masih lebih dari 800 karakter, POTONG PAKSA per kata!
        if len(p) > max_chars:
            if current_chunk:
                sub_chunks.append(current_chunk.strip())
                current_chunk = ""
                
            words = p.split(' ')
            temp = ""
            for w in words:
                if len(temp) + len(w) + 1 > max_chars:
                    sub_chunks.append(temp.strip())
                    temp = w + " "
                else:
                    temp += w + " "
            if temp.strip():
                sub_chunks.append(temp.strip())
            continue

        # Jika baris/paragraf ini muat, gabungkan ke current_chunk
        if len(current_chunk) + len(p) <= max_chars:
            current_chunk += p + "\n"
        else:
            if current_chunk: 
                sub_chunks.append(current_chunk.strip())
            current_chunk = p + "\n"
            
    if current_chunk.strip():
        sub_chunks.append(current_chunk.strip())
        
    return sub_chunks


def dynamic_chunker(text: str, meta: dict) -> list[dict]:
    chunks = []
    doc_type = meta["doc_type"]
    
    sections = []
    extraction_method = ""

    if doc_type == "sop":
        # Lapis 1: coba potong pakai header markdown (###)
        sections = re.split(r'\n(?=#{1,4}\s)', text)
        extraction_method = "Markdown Headers"
        
        # Lapis 2: kalau heading markdown tidak ketemu, pakai Heuristik Header OCR
        if len(sections) < 5:
            log.warning(f"  [!] Markdown headings gagal, mencoba Heuristik Header OCR...")
            # tangkap: BAB/Pasal, baris KAPITAL semua, atau angka bernomor "1. UMUM"
            header_pattern = r'\n(?=(?:BAB\s*[IVX\d]+|Pasal\s*\d+|\d+\.\s+[A-Z]{2,}|[A-Z][A-Z\s\-\(\)]{4,60}(?=\n)))'
            sections = re.split(header_pattern, text)
            extraction_method = "OCR Heuristic"

    elif doc_type in ["glosarium", "spartan"]:
        sections = re.split(r'\n(?=[A-Z][^\n]{1,50}\n)', text)
        extraction_method = "Glosarium Pattern"

    # Lapis 3: jika semua strategi di atas gagal (atau doc_type == "umum")
    if len(sections) <= 1:
        log.warning(f"  [!] Strategi {doc_type} gagal. Menggunakan Global Fallback.")
        sections = [text]
        extraction_method = "Global Fallback"

    # ==========================================
    # PROSES PEMOTONGAN FINAL (MENGGUNAKAN FORCE SPLIT)
    # ==========================================
    for sec in sections:
        sec = sec.strip()
        if not sec or len(sec) < 20: continue
        
        # Ekstrak judul dari baris pertama yang tidak kosong
        # 1. pecah per baris
        lines = [line.strip() for line in sec.split('\n') if line.strip()] 
        
        # 2. ambil baris pertama yang valid
        if lines:
            first_line = lines[0]
            # 3. bersihkan dari tanda markdown #
            title = re.sub(r'[#\*]+', '', first_line).strip()
            
            # 4. jika judulnya kepanjangan (bukan heading asli), potong atau beri label default
            if len(title) > 80:
                title = title[:77] + "..."
        else:
            title = "Bagian Tanpa Judul"
        # Tentukan metadata spesifik
        if doc_type in ["glosarium", "spartan"]:
            if title.startswith("Glosarium") or title.startswith("Kamus"): continue
            chunk_meta = {**meta, "term": title}
        elif doc_type == "sop" and extraction_method != "Global Fallback":
            chunk_meta = {**meta, "section": title if title else "Bagian Tanpa Judul"}
        else:
            chunk_meta = meta

        # [KUNCI UTAMA]: Paksa potong jika panjangnya > 800 karakter!
        sub_texts = force_split_text(sec, max_chars=800)
        
        for sub_text in sub_texts:
            chunks.append({"text": sub_text, "metadata": chunk_meta})

    return chunks

# ==========================================
# 4. GEMINI API & DATABASE TRANSACTION
# ==========================================
def get_embedding(text: str):
    try:
        response = client.models.embed_content(
            model="gemini-embedding-001", contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768)
        )
        time.sleep(0.5) # Pacing
        return response.embeddings[0].values
    except Exception as e:
        log.error(f"Gemini API Error: {e}")
        return None

def process_file(file_path: Path):
    raw_text = extract_text_from_file(file_path)
    if not raw_text: return

    cleaned_text = clean_text(raw_text)
    meta = infer_metadata(file_path, cleaned_text)
    chunks = dynamic_chunker(cleaned_text, meta)
    
    log.info(f"File {file_path.name} ({meta['doc_type']}) -> {len(chunks)} chunks dihasilkan.")
    if not chunks: return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    try:
        # IDEMPOTENCY CHECK
        doc_hash = hashlib.sha256(cleaned_text.encode('utf-8')).hexdigest()
        cur.execute("SELECT id, content_hash FROM documents WHERE source_url = %s", (str(file_path),))
        doc_row = cur.fetchone()
        
        if doc_row and doc_row[1] == doc_hash:
            log.info(f"  -> Skip (Hash sama): {file_path.name}")
            return

        if doc_row:
            doc_id = doc_row[0]
            cur.execute("UPDATE documents SET content=%s, content_hash=%s, metadata=%s, updated_at=NOW() WHERE id=%s", 
                        (cleaned_text, doc_hash, Json(meta), doc_id))
            cur.execute("DELETE FROM embeddings WHERE document_id=%s", (doc_id,))
        else:
            cur.execute("INSERT INTO documents (source_url, title, content, content_hash, metadata) VALUES (%s, %s, %s, %s, %s) RETURNING id", 
                        (str(file_path), file_path.name, cleaned_text, doc_hash, Json(meta)))
            doc_id = cur.fetchone()[0]

        success_count = 0
        for i, chunk in enumerate(chunks):
            log.info(f"   -> Embed Chunk {i+1}/{len(chunks)}")
            vector = get_embedding(chunk["text"])
            if not vector: 
                log.warning(f"  [!] Gagal embed chunk {i+1}, skip.")
                continue
            
            chunk_hash = hashlib.sha256(chunk["text"].encode('utf-8')).hexdigest()
            cur.execute("INSERT INTO embeddings (document_id, chunk_index, chunk_text, content_hash, embedding, metadata) VALUES (%s, %s, %s, %s, %s, %s)",
                        (doc_id, i, chunk["text"], chunk_hash, vector, Json(chunk["metadata"])))
            success_count += 1

        # FAIL-FAST CHECK
        if success_count == 0:
            conn.rollback()
            log.error(f"  [!] GAGAL TOTAL: 0 chunk ter-embed. Rollback!")
        else:
            conn.commit()
            log.info(f"  [v] Sukses menyimpan {success_count} chunk.")
    except Exception as e:
        conn.rollback()
        log.error(f"Database Error: {e}")
    finally:
        cur.close()
        conn.close()

# ==========================================
# 5. MAIN (DYNAMIC DISCOVERY)
# ==========================================
def main():
    if not RAW_DIR.exists():
        log.error(f"Folder {RAW_DIR} tidak ditemukan.")
        return

    # Ambil semua .pdf dan .txt, abaikan .ocr.txt
    files = [f for f in RAW_DIR.iterdir() if f.is_file() and f.suffix.lower() in ['.pdf', '.txt'] and not f.name.endswith('.ocr.txt')]
    
    log.info(f"Menemukan {len(files)} file untuk diproses.")
    for file_path in files:
        log.info(f"\n{'='*40}\nMemproses: {file_path.name}")
        process_file(file_path)

if __name__ == "__main__":
    main()
