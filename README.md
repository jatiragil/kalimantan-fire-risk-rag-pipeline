# 🔥 Kalimantan Peatland Fire Risk Intelligence

An End-to-End Data & AI Pipeline for Peatland Fire Risk Mitigation in Kalimantan.
Bridging the gap between raw weather data and actionable fire risk intelligence.

## **Why this project?**

Most of my previous projects relied on clean, pre-packaged e-commerce datasets. I wanted to build something with actual friction. Peatland fires (Karhutla) in Kalimantan presented a perfect engineering challenge: it's a messy, high-stakes problem where a single miscalculated threshold or a hallucinated AI response can actually mean a false alarm (or worse, a missed one). I built this pipeline to see if a Modern Data Stack could handle the unpredictability of real-world climatology.

[📸 SCREENSHOT 1: Taruh gambar tabel Streamlit Anda di sini]

*Dashboard showing 5-level risk assessment (Calibrated via P90 historical data).*

[📸 SCREENSHOT 2: Taruh gambar Chatbot AI Anda di sini]

*Hybrid RAG Assistant answering a query with contextual citations from BMKG documents.*

## 📂 Project Structure

```text
kalimantan-fire-risk-rag-pipeline/
├── dags/                  # Airflow DAG definitions
├── dashboard/             # Streamlit UI (app.py)
├── data/                  # Raw documents (JSON snapshots)
├── docs/                  # Screenshots for README
├── src/                   # Python ETL & Ingestion code
├── weather_analytics/     # dbt project (Staging, Marts, Schema)
├── .env.example           # Environment variables template
├── docker-compose.yml     # Airflow orchestration
├── requirements.txt       # Python dependencies
└── README.md
```

## 🏗️ Architecture & Data Flow

This project uses a Dual-Pipeline architecture:

- **Weather Pipeline:** Python fetches 10 years of historical data and 7 days of forecast from Open-Meteo API. It is stored in Neon PostgreSQL, transformed via dbt, and modeled into a Star Schema.

- **Knowledge Pipeline:** BMKG documents are chunked, embedded using Gemini API, and stored in pgvector.

- **Orchestration:** Airflow (Dockerized) schedules the ingestion and transformation.

- **Serving:** Streamlit displays the dashboard and serves the Hybrid RAG Chatbot.

## 🧠 Key Engineering Decisions

- **Why Rule-Based Climatology?** I intentionally avoided Machine Learning. In wildfire prediction, ML requires historical labeled hotspot data (which is scarce). Instead, I used a transparent, rule-based approach aligned with the Fire Weather Index (FWI) standard. The risk is calculated using a 7-day rolling window of Temperature, Precipitation, Wind Speed, and Relative Humidity.

- **The "Hybrid RAG" Trick:** LLMs lack numerical precision. If asked "What is the temperature tomorrow?", an LLM might hallucinate. So, I built a hybrid system: Python fetches the exact numbers via SQL and injects them into the prompt, while pgvector retrieves the contextual BMKG rules. The AI is forced to be a narrator, not a calculator.

- **Graceful Degradation:** Free-tier APIs are a double-edged sword. To ensure the demo never breaks, I built a multi-provider fallback chain (IteraCompute -> OpenRouter -> Gemini) with a strict 10-second timeout. It makes the system feel robust, even under resource constraints.

## 🚧 Challenges & Trade-offs

- **Surviving on 3.3GB of RAM:** Running the full Airflow stack alongside Streamlit on my 3.3GB RAM laptop caused constant OOM (Out of Memory) errors. The Fix: I used Docker Compose Profiles. Now, Airflow (profile: airflow) and Streamlit (profile: dashboard) never run at the same time. It forced me to understand container resource isolation.

- **The HuggingFace Deprecation (And a Schema Evolution):** Mid-development, HuggingFace changed its API policy. I migrated to Google Gemini Embeddings. The catch? Gemini outputs 768-dimensional vectors, while HuggingFace was 384. The Fix: I performed a database Schema Evolution (ALTER TABLE) to change the vector dimension without dropping the existing 10-year weather data.

- **Trusting the Data Over My Gut:** Initially, I set the "Extreme Risk" wind speed threshold at 20 km/h. But when I ran the numbers, Kalimantan (being equatorial) rarely gets winds that high. The Fix: I queried the PERCENTILE_CONT(0.90) of 10 years of local wind data. The result was 14.5 km/h. I changed the threshold. It was a humbling reminder that domain knowledge must be backed by data, not assumptions.

- **The SQL "Edge Effect":** When using RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND '3 days' FOLLOWING for the forecast, the last day of the dataset always yielded NULL. The Fix: I filtered out NULL values in the Streamlit query so the dashboard only displays valid predictions, preventing the UI from crashing.

## ⚠️ Limitations

- The current RAG uses a static JSON snapshot of BMKG documents. In a real production environment, this would be an automated scraper running via Airflow.

- Streamlit is run locally (not in Docker) to conserve RAM, while Airflow runs in Docker.

- The rule-based system is a proxy. It is not a full physical model like the Canadian Forest Fire Weather Index (FWI).

## 🚀 How to Run (Local Reproducibility)

### 1. Clone & Setup Environment

```bash
git clone https://github.com/jatiragil/kalimantan-fire-risk-rag-pipeline.git
cd kalimantan-fire-risk-rag-pipeline
cp .env.example .env
```

*Note: Open .env and fill in your actual DATABASE_URL and GEMINI_API_KEY.

Gemini (Required): Get it for free at Google AI Studio.

IteraCompute & OpenRouter (Optional): Used for the Multi-Provider Fallback feature. If left empty, the system will gracefully skip them. Get them at IteraCompute and OpenRouter.*

### 2. Database & dbt Setup

```bash
python -m src.setup_db
python -m src.ingest_weather
cd weather_analytics && dbt run && dbt test && cd ..
```

### 3. Run Streamlit (Local UI)

```bash
streamlit run dashboard/app.py
```

### 4. (Optional) Run Airflow via Docker

Because of local RAM constraints, Airflow is isolated using Docker Compose Profiles.

```bash
docker compose --profile airflow up -d
```

## 🧪 Evaluation: Anti-Hallucination & Guardrails

To prove the system is factual and cannot be tricked into hallucinating, I ran a "Golden Dataset" test using a custom `evaluate.py` script. The script tests three distinct scenarios: Data Retrieval (SQL), Document Retrieval (RAG), and Out-of-Scope Guardrails.

| Test Type | Question | AI Response (Excerpt) | Expected Behavior |
| :--- | :--- | :--- | :--- |
| **In-Scope (Weather)** | *"Bagaimana cuaca besok?"* | *"(1) Kesimpulan Utama: Berisiko Tinggi (Status: Waspada Karhutla)... (2) Penjelasan Klimatologi: Suhu permukaan mencapai 32.9°C..."* | Accurate number retrieved from SQL database. |
| **In-Scope (Document)** | *"Apa itu FFMC dan mengapa penting?"* | *"(1) Kesimpulan Utama: Ya, sangat penting... (2) Penjelasan: FFMC (Fine Fuel Moisture Code) adalah indeks yang digunakan untuk mengukur kadar air..."* | Accurate definition retrieved from pgvector (BMKG doc). |
| **Out-of-Scope** | *"Siapa presiden Indonesia?"* | *"Saya adalah spesialis cuaca dan karhutla Kalimantan, saya tidak bisa menjawab di luar topik tersebut."* | **Polite Refusal.** Guardrail works perfectly. |

*The system successfully refuses to answer out-of-scope questions, proving that the prompt engineering and RAG boundaries are working as intended. If the AI cannot find the answer in the provided SQL data or BMKG documents, it is explicitly designed to admit its limitations rather than hallucinate.*

(Access Airflow UI at http://localhost:8080)

## 🔮 Future Work

- Integrating real-time satellite hotspot data (NASA FIRMS) to replace the rule-based proxy.

- Migrating Airflow to AWS MWAA for 24/7 scheduling without local hardware constraints.

- Adding a visual map (Leaflet) for better spatial risk visualization.

---

Author: Jati Ragil | GitHub | LinkedIn
