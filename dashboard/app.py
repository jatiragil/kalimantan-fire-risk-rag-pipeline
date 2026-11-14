import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
import logging

# IMPORT OTAK RAG DARI FILE TERPISAH
from src.rag_engine import ask_chatbot

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Karhutla Intelligence", page_icon="🔥", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_db_engine():
    db_url = os.getenv("DATABASE_URL").replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(db_url, pool_pre_ping=True)

engine = get_db_engine()

# --- FUNGSI CACHING DASHBOARD ---
@st.cache_data(ttl=600)
def load_risk_data():
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

# --- UI UTAMA ---
st.title("Kalimantan Fire Risk Intelligence")
st.markdown("Sistem Peringatan Dini Karhutla berbasis Data Cuaca & AI.")

# Sidebar
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
        if val == 'EKSTREM': return 'background-color: #800080; color: white;'
        elif val == 'AWAS': return 'background-color: #ff0000; color: white;'
        elif val == 'SIAGA': return 'background-color: #ff8c00; color: white;'
        elif val == 'WASPADA': return 'background-color: #ffd700; color: black;'
        else: return 'background-color: #21c354; color: white;'
    
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
                jawaban, konteks, _ = ask_chatbot(prompt, kota_pilihan)
                st.markdown(jawaban)
                with st.expander("Lihat Sumber Dokumen"):
                    st.write(konteks)
                    
        st.session_state.messages.append({"role": "assistant", "content": jawaban})
