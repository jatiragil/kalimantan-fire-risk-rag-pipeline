import os
import sys
import logging
import requests
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")

def get_coordinates(city_name: str):
    log.info(f"Mencari koordinat untuk: {city_name}...")
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={city_name}&count=1&language=id&format=json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "results" not in data:
            log.warning(f"Kota {city_name} tidak ditemukan di Open-Meteo.")
            return None, None
            
        lat = data["results"][0]["latitude"]
        lon = data["results"][0]["longitude"]
        return lat, lon
    except requests.RequestException as e:
        log.error(f"Gagal mengambil koordinat: {e}")
        return None, None

def fetch_weather_data(lat: float, lon: float, source: str, start_date=None, end_date=None):
    # Validasi ketat untuk mencegah typo
    if source not in ["archive", "forecast"]:
        log.error(f"Source tidak valid: '{source}'. Harus 'archive' atau 'forecast'.")
        sys.exit(1)

    log.info(f"Mengambil data {source} untuk koordinat: {lat}, {lon}...")
    
    if source == "archive":
        if not start_date or not end_date:
            log.error("Untuk data archive, start_date dan end_date wajib diisi.")
            sys.exit(1)
            
        log.info(f"Rentang historis: {start_date} s/d {end_date}")
        
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&daily=temperature_2m_max,precipitation_sum,wind_speed_10m_max"
            f"&daily=temperature_2m_max,precipitation_sum,wind_speed_10m_max,relative_humidity_2m_mean"
            f"&timezone=Asia%2FJakarta"
        )
    else:
        # Data forecast (7 hari ke depan)
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,precipitation_sum,wind_speed_10m_max"
            f"&daily=temperature_2m_max,precipitation_sum,wind_speed_10m_max,relative_humidity_2m_mean"
            f"&timezone=Asia%2FJakarta"
        )
        
    try:
        response = requests.get(url, timeout=30) 
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        log.error(f"Gagal mengambil data cuaca: {e}")
        return None

def save_to_db(city_name: str, weather_data: dict, source: str):
    if not weather_data or "daily" not in weather_data:
        log.warning(f"Data kosong untuk {city_name} ({source}). Dilewati.")
        return

    log.info(f"Menyimpan data {source} untuk {city_name} ke database...")
    
    dates = weather_data["daily"]["time"]
    temps = weather_data["daily"]["temperature_2m_max"]
    precip = weather_data["daily"]["precipitation_sum"]
    winds = weather_data["daily"]["wind_speed_10m_max"]
    humidities = weather_data["daily"]["relative_humidity_2m_mean"]
    
    records = []
    for i in range(len(dates)):
        records.append((
            city_name, 
            dates[i], 
            temps[i], 
            precip[i],
            winds[i],
            humidities[i],
            source
        ))

    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                query = """
                    INSERT INTO raw_weather (city_name, observation_date, temperature_max, precipitation_sum, wind_speed_max, relative_humidity_mean, data_source)
                    VALUES %s
                    ON CONFLICT (city_name, observation_date) DO UPDATE 
                    SET temperature_max = EXCLUDED.temperature_max,
                        precipitation_sum = EXCLUDED.precipitation_sum,
                        wind_speed_max = EXCLUDED.wind_speed_max,
                        relative_humidity_mean = EXCLUDED.relative_humidity_mean,
                        data_source = EXCLUDED.data_source,
                        ingested_at = NOW()
                    WHERE raw_weather.temperature_max IS DISTINCT FROM EXCLUDED.temperature_max
                       OR raw_weather.precipitation_sum IS DISTINCT FROM EXCLUDED.precipitation_sum
                       OR raw_weather.wind_speed_max IS DISTINCT FROM EXCLUDED.wind_speed_max
                       OR raw_weather.relative_humidity_mean IS DISTINCT FROM EXCLUDED.relative_humidity_mean;
                """
                execute_values(cur, query, records)
            conn.commit()
        log.info(f"Sukses menyimpan {len(records)} baris data {source} untuk {city_name}.")
    except psycopg2.Error as e:
        log.error(f"Database error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if not DB_URL:
        log.error("DATABASE_URL tidak ditemukan.")
        sys.exit(1)

    # Daftar kota (termasuk ibu kota provinsi di Kalimantan untuk mitigasi Karhutla)
    daftar_kota = [
        "Bogor", 
        "Jakarta", 
        "Surabaya",
        "Pontianak",      # Mewakili Kalimantan Barat
        "Palangkaraya",   # Mewakili Kalimantan Tengah
        "Banjarmasin",    # Mewakili Kalimantan Selatan
        "Samarinda",      # Mewakili Kalimantan Timur
        "Tarakan"         # Mewakili Kalimantan Utara
    ]

    # Tanggal dinamis: Tepat 10 tahun ke belakang dari hari ini
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=365 * 10) # 10 tahun ke belakang

    log.info(f"Memulai Backfill data dari {start_date} hingga {end_date}")

    for kota in daftar_kota:
        log.info(f"=== Memproses {kota} ===")
        lat, lon = get_coordinates(kota)
        
        if lat is not None and lon is not None:
            # 1. Ambil Data Historis 10 Tahun
            archive_data = fetch_weather_data(
                lat, lon, 
                source="archive", 
                start_date=start_date, 
                end_date=end_date
            )
            if archive_data:
                save_to_db(kota, archive_data, source="archive")
            
            # 2. Ambil Data Forecast 7 Hari
            forecast_data = fetch_weather_data(lat, lon, source="forecast")
            if forecast_data:
                save_to_db(kota, forecast_data, source="forecast")
        else:
            log.error(f"Gagal mendapatkan koordinat untuk {kota}.")

    log.info("Proses Ingestion Selesai!")
