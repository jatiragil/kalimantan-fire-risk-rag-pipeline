import os
import pandas as pd
from sqlalchemy import create_engine, text
from google import genai
from google.genai import types
import openai
from dotenv import load_dotenv
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- KONEKSI DATABASE ---
db_url = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+psycopg2://", 1)
engine = create_engine(db_url, pool_pre_ping=True)

# --- INISIALISASI CLIENT AI ---
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

itera_key = os.getenv("ITERACOMPUTE_API_KEY")
itera_client = openai.OpenAI(
    base_url="https://api.iteracompute.com/v1", 
    api_key=itera_key
) if itera_key else None

openrouter_key = os.getenv("OPENROUTER_API_KEY")
openrouter_client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openrouter_key
) if openrouter_key else None


def ask_chatbot(user_question, city_context):
    # 1. Ambil data cuaca
    query_weather = text("""
        SELECT observation_date, risk_status_forecast, avg_temp_forecast_3d, avg_rain_forecast_3d,
               avg_wind_forecast_3d, avg_rh_forecast_3d
        FROM fct_fire_risk 
        WHERE city_name = :city AND data_source = 'forecast'
          AND avg_temp_forecast_3d IS NOT NULL
        ORDER BY observation_date ASC LIMIT 3;
    """)
    with engine.connect() as conn:
        df_risk = pd.read_sql(query_weather, conn, params={"city": city_context})
    
    weather_context = "Data prakiraan cuaca tidak tersedia."
    if not df_risk.empty:
        weather_context = f"Berikut adalah data prakiraan cuaca 3 hari ke depan untuk {city_context}:\n"
        for _, row in df_risk.iterrows():
            weather_context += (
                f"- Tanggal {row['observation_date']}: "
                f"Suhu {row['avg_temp_forecast_3d']:.1f}°C, Hujan {row['avg_rain_forecast_3d']:.1f}mm, "
                f"Angin {row['avg_wind_forecast_3d']:.1f} km/jam, RH {row['avg_rh_forecast_3d']:.1f}%, "
                f"Status: {row['risk_status_forecast']}.\n"
            )

    # 2. Embed pertanyaan user
    resp = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=user_question,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=768)
    )
    query_vector = resp.embeddings[0].values

    # 3. Vector Search (MENGGUNAKAN METADATA)
    query_sql = text("""
        SELECT e.chunk_text, e.metadata, d.title, d.source_url
        FROM embeddings e
        JOIN documents d ON e.document_id = d.id
        ORDER BY e.embedding <=> :vector
        LIMIT 6;
    """)
    with engine.connect() as conn:
        df_doc = pd.read_sql(query_sql, conn, params={"vector": str(query_vector)})
    
    doc_context = ""
    retrieved_metas = []
    
    for _, row in df_doc.iterrows():
        meta = row['metadata'] if row['metadata'] else {}
        retrieved_metas.append(meta)
        section_info = meta.get('section', meta.get('term', 'Bagian Umum'))
        
        doc_context += f"\n[Sumber: {row['title']} | Bagian: {section_info} | URL: {row['source_url']}]\n{row['chunk_text']}\n"

    # 4. Susun Prompt (R-C-T-F + Anti-Halusinasi + BLUF)
    prompt = f"""
Anda adalah Analis Cuaca Senior BMKG Spesialis Karhutla Kalimantan. 
Gaya bicara Anda: Presisi, tegas, dan analitis.

ATURAN MUTLAK (ANTI-HALUSINASI):
1. JAWABLAH HANYA berdasarkan data yang ada di [DATA CUACA] dan [DOKUMEN BMKG].
2. JIKA jawaban dari pertanyaan pengguna TIDAK ADA di dalam [DOKUMEN BMKG] atau [DATA CUACA], Anda WAJIB menjawab: "Maaf, informasi tersebut tidak disebutkan di dalam dokumen yang tersedia." JANGAN mengarang jawaban.
3. JIKA pertanyaan di luar topik Karhutla/Cuaca, TOLAK dengan sopan MENGGUNAKAN KALIMAT PERSIS INI: "Sebagai sistem spesialis cuaca dan karhutla Kalimantan, saya tidak memiliki kapasitas untuk menjawab pertanyaan di luar domain tersebut."
4. JANGAN mengarang data atau referensi.

DATA YANG TERSEDIA:
[DATA CUACA]:
{weather_context}

[DOKUMEN BMKG]:
{doc_context}

INSTRUKSI JAWABAN:
1. JIKA PENGGUNA BERTANYA TENTANG RISIKO KEBAKARAN / CUACA SAAT INI (Hybrid Query):
   Anda WAJIB menggabungkan [DATA CUACA] dan [DOKUMEN BMKG].
   Format jawaban:
   (1) 🎯 KESIMPULAN UTAMA (Status Risiko & Tindakan Mitigasi)
   (2) 🧠 PENJELASAN KLIMATOLOGI (Wajib kaitkan angka cuaca seperti RH/Suhu dengan aturan/kriteria di [DOKUMEN BMKG]. Jangan hanya mengutip teori umum!)
   (3) 📅 RINCIAN HARIAN (Wajib sebutkan angka Suhu, RH, dan Hujan dari [DATA CUACA] per tanggal)
   (4) 📊 REFERENSI (Sebutkan [Bagian: ...] dari dokumen yang mendasari analisis)

2. JIKA PENGGUNA BERTANYA TENTANG DEFINISI / PROSEDUR MURNI (Misal: "Apa itu FFMC?"):
   JANGAN membahas cuaca atau tanggal. Jawablah dengan format mengalir:
   - pastikan diawali atau disisipi frasa "Menurut dokumen BMKG yang tersedia..." di paragraf pertama.
   - Penjelasan Detail (sebutkan [Bagian: ...]). dengan list jika dibutuhkan
   - Referensi

Pertanyaan Pengguna: {user_question}
Jawaban Anda:
"""
    # --- FALLBACK STRATEGY ---
    try:
        response = gemini_client.models.generate_content(model='gemini-3.5-flash-lite', contents=prompt)
        return response.text, doc_context, retrieved_metas
    except Exception as e:
        logger.warning(f"Gemini gagal: {e}. Fallback...")

    if itera_client:
        try:
            response = itera_client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[{"role": "user", "content": prompt}], temperature=0.1, timeout=5.0)
            return response.choices[0].message.content, doc_context, retrieved_metas
        except Exception as e:
            logger.warning(f"Itera gagal: {e}. Fallback...")

    if openrouter_client:
        try:
            response = openrouter_client.chat.completions.create(model="meta-llama/llama-3.3-70b-instruct", messages=[{"role": "user", "content": prompt}], temperature=0.1, timeout=10.0)
            return response.choices[0].message.content, doc_context, retrieved_metas
        except Exception as e:
            logger.error(f"Semua AI gagal. Error: {e}")
            
    return "Maaf, layanan AI sedang sibuk.", doc_context, retrieved_metas
