import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from google import genai
from google.genai import types
import openai
import os
from dotenv import load_dotenv
import logging

load_dotenv()

# Setup Logging untuk Backend
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Karhutla Intelligence", page_icon="🔥", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_db_engine():
    db_url = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(db_url, pool_pre_ping=True)

engine = get_db_engine()

# --- INISIALISASI CLIENT AI ---
# 1. Gemini
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 2. IteraCompute
itera_key = os.getenv("ITERACOMPUTE_API_KEY")
itera_client = openai.OpenAI(
    base_url="https://api.iteracompute.com/v1", 
    api_key=os.getenv("ITERACOMPUTE_API_KEY")
) if itera_key else None

# 3. OpenRouter
openrouter_key = os.getenv("OPENROUTER_API_KEY")
openrouter_client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
) if openrouter_key else None

# --- FUNGSI CACHING ---
@st.cache_data(ttl=600)
def load_risk_data():
    # Filter hanya untuk 5 kota di Kalimantan (Fokus Niche)
    query = text("""
        SELECT DISTINCT ON (city_name) 
            city_name, observation_date, risk_status_forecast, 
            avg_temp_forecast_3d, avg_rain_forecast_3d, avg_wind_forecast_3d, avg_rh_forecast_3d
        FROM fct_fire_risk
        WHERE data_source = 'forecast' 
          AND avg_temp_forecast_3d IS NOT NULL
          AND city_name IN ('Pontianak', 'Palangkaraya', 'Banjarmasin', 'Samarinda', 'Tarakan')
        ORDER BY city_name, observation_date ASC; 
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


@st.cache_data(ttl=600)
def load_monthly_trend(city):
    query = text("""
        SELECT 
            DATE_TRUNC('month', observation_date) as month,
            AVG(temperature_max) as avg_temp,
            SUM(precipitation_sum) as total_rain
        FROM stg_weather
        WHERE city_name = :city AND data_source = 'archive'
        GROUP BY DATE_TRUNC('month', observation_date)
        ORDER BY month;
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"city": city})

# --- FUNGSI RAG (Hybrid + Citations) ---
def ask_chatbot(user_question, city_context):
    # 1. Ambil data cuaca
    query_weather = text("""
        SELECT 
            observation_date, 
            risk_status_forecast, 
            avg_temp_forecast_3d, 
            avg_rain_forecast_3d,
            avg_wind_forecast_3d,
            avg_rh_forecast_3d
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
            # Kita tambahkan keterangan tanggal secara eksplisit
            weather_context += (
                f"- Tanggal {row['observation_date']}: "
                f"Suhu {row['avg_temp_forecast_3d']:.1f}°C, "
                f"Hujan {row['avg_rain_forecast_3d']:.1f}mm, "
                f"Angin {row['avg_wind_forecast_3d']:.1f} km/jam, "
                f"RH {row['avg_rh_forecast_3d']:.1f}%, "
                f"Status: {row['risk_status_forecast']}.\n"
            )

    # 2. Embed pertanyaan user (Gemini Embedding)
    resp = gemini_client.models.embed_content(
        model="gemini-embedding-001",
        contents=user_question,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=768)
    )
    query_vector = resp.embeddings[0].values

    # 3. Vector Search (JOIN untuk Sitasi)
    query_sql = text("""
        SELECT e.chunk_text, d.title, d.source_url
        FROM embeddings e
        JOIN documents d ON e.document_id = d.id
        ORDER BY e.embedding <=> :vector
        LIMIT 3;
    """)
    with engine.connect() as conn:
        df_doc = pd.read_sql(query_sql, conn, params={"vector": str(query_vector)})
    
    doc_context = ""
    for _, row in df_doc.iterrows():
        doc_context += f"\n[Sumber: {row['title']} ({row['source_url']})]\n{row['chunk_text']}\n"

    # 4. Susun Prompt (Versi R-C-T-F + Chain of Thought)
    prompt = f"""
    [ROLE]
    Kamu adalah Ahli Klimatologi BMKG Spesialis Karhutla Kalimantan. Kamu sangat memahami lahan gambut, El Nino, RH, dan cuaca ekstrem.

    [CONTEXT]
    Kamu diberikan dua sumber data:
    1. DATA CUACA: Angka prakiraan (suhu, hujan, angin, RH) untuk {city_context}.
    2. DOKUMEN BMKG: Teks SOP, definisi, dan berita terkait karhutla.

    [TASK & FORMAT (BLUF)]
    1. Jawablah dengan format BLUF: (1) Kesimpulan Utama (Ya/Tidak/Berisiko Tinggi/Rendah), (2) Penjelasan Klimatologi, (3) Rincian Harian (Gunakan bullet points dan sebutkan tanggalnya secara eksplisit berdasarkan DATA CUACA), (4) Data Pendukung.
    2. JIKA pertanyaan di luar topik Karhutla/Cuaca Kalimantan, TOLAK dengan sopan: "Saya adalah spesialis cuaca dan karhutla Kalimantan, saya tidak bisa menjawab di luar topik tersebut."
    3. JANGAN mengarang data. Jika [DATA CUACA] kosong, katakan datanya belum tersedia.

    [DATA CUACA]:
    {weather_context}

    [DOKUMEN BMKG]:
    {doc_context}

    Pertanyaan Pengguna: {user_question}
    """

    # --- STRATEGI FALLBACK BERLAPIS ---
    
    # Lapis 1: Gemini 3.5 Flash
    try:
        response = gemini_client.models.generate_content(
            model='gemini-3.5-flash-lite', 
            contents=prompt
        )
        return response.text, doc_context
    except Exception as e:
        logger.warning(f"Gemini gagal: {e}. Beralih ke lapisan berikutnya...")

    # Lapis 2: IteraCompute (hanya jalan jika API Key diisi)
    if itera_client:
        try:
            response = itera_client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                timeout=5.0
            )
            return response.choices[0].message.content, doc_context
        except Exception as e:
            logger.warning(f"IteraCompute gagal: {e}. Beralih ke OpenRouter...")

    # Lapis 3: OpenRouter (hanya jalan jika API Key diisi)
    if openrouter_client:
        try:
            response = openrouter_client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct", 
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                timeout=10.0
            )
            return response.choices[0].message.content, doc_context
        except Exception as e:
            logger.error(f"Semua AI gagal. Error terakhir: {e}")
            
    # Jika semua lapisan di atas gagal atau di-skip
    return "Maaf, layanan AI sedang sibuk atau belum dikonfigurasi. Silakan coba beberapa saat lagi.", doc_context

# --- UI UTAMA ---
st.title("🔥 Kalimantan Fire Risk Intelligence")
st.markdown("Sistem Peringatan Dini Karhutla berbasis Data Cuaca & AI.")

# Sidebar untuk memilih kota
st.sidebar.header("Pilih Wilayah")
df_risk_awal = load_risk_data()
kota_pilihan = st.sidebar.selectbox("Kota/Kabupaten:", df_risk_awal['city_name'].unique())

st.sidebar.markdown("---")
st.sidebar.caption("Created by **Jati Ragil**")
st.sidebar.caption("[GitHub](https://github.com/jatiragil) | [LinkedIn](https://linkedin.com/in/jatiragil)")

tab1, tab2 = st.tabs(["📊 Dashboard Risiko (Forecast)", "🤖 AI Assistant"])

with tab1:
    st.header(f"Status Risiko Karhutla 3 Hari ke Depan: {kota_pilihan}")
    
    df_kota = df_risk_awal[df_risk_awal['city_name'] == kota_pilihan]
    
    def color_status(val):
        if val == 'EKSTREM': return 'background-color: #800080; color: white;' # Ungu
        elif val == 'AWAS': return 'background-color: #ff0000; color: white;' # Merah
        elif val == 'SIAGA': return 'background-color: #ff8c00; color: white;' # Oranye
        elif val == 'WASPADA': return 'background-color: #ffd700; color: black;' # Kuning
        else: return 'background-color: #21c354; color: white;' # Hijau (AMAN)
    
    # Rename kolom
    df_display = df_kota.copy()
    df_display = df_display.rename(columns={
        'city_name': 'Wilayah',
        'observation_date': 'Tanggal',
        'risk_status_forecast': 'Status Risiko',
        'avg_temp_forecast_3d': 'Suhu (°C)',
        'avg_rain_forecast_3d': 'Hujan (mm)',
        'avg_wind_forecast_3d': 'Angin (km/j)',
        'avg_rh_forecast_3d': 'Kelembapan (%)'
    })
  
    st.dataframe(df_display.style.map(color_status, subset=['Status Risiko']), width="stretch")
    st.divider()
    st.header("Tren Historis (10 Tahun)")
    df_trend = load_monthly_trend(kota_pilihan)
    
    fig = px.line(df_trend, x='month', y='avg_temp', title=f"Rata-rata Suhu Bulanan - {kota_pilihan}")
    st.plotly_chart(fig, width="stretch")

with tab2:
    st.header(f"Tanya AI Seputar Cuaca & Karhutla ({kota_pilihan})")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Contoh: Mengapa wilayah ini berisiko tinggi?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Menganalisis data & dokumen..."):
                jawaban, konteks = ask_chatbot(prompt, kota_pilihan)
                st.markdown(jawaban)
                with st.expander("Lihat Sumber Dokumen"):
                    st.write(konteks)
                    
        st.session_state.messages.append({"role": "assistant", "content": jawaban})
