import sys
import logging
logging.getLogger("httpx").setLevel(logging.ERROR)
from src.rag_engine import ask_chatbot

# ==========================================
# 1. GOLDEN DATASET (Kertas Ujian)
# ==========================================
# Format: 
# - expected_doc_type: Tipe dokumen yang WAJIB diambil (None jika out-of-scope)
# - expected_keywords: Kata kunci yang WAJIB ada di jawaban LLM
TEST_CASES = [
    {
        "id": 1,
        "category": "Definisi",
        "question": "Apa itu FFMC dan mengapa penting?",
        "expected_doc_type": ["glosarium", "spartan", "sop"],
        "expected_keywords": ["fine fuel", "bahan"] 
    },
    {
        "id": 2,
        "category": "SOP Umum",
        "question": "Apa maksud dan tujuan dari SOP BMKG ini?",
        "expected_doc_type": ["sop"],
        "expected_keywords": ["keseragaman", "acuan"]
    },
    {
        "id": 3,
        "category": "SOP Spesifik",
        "question": "Siapa yang melaksanakan penyediaan informasi peringatan dini di tingkat Provinsi?",
        "expected_doc_type": ["sop"],
        "expected_keywords": ["UPT", "Unit Pelaksana Teknis"] 
    },
    {
        "id": 4,
        "category": "Guardrail (Out of Scope)",
        "question": "Siapa presiden Indonesia?",
        "expected_doc_type": None,
        "expected_keywords": ["spesialis", "domain"]
    },
    {   "id": 5,
        "category": "Cuaca (Hybrid Query)",
        # PERTANYAAN CUACA: Harus mengambil data dari fct_fire_risk
        "question": "Bagaimana prakiraan cuaca dan risiko karhutla di Pontianak 3 hari ke depan?",
        "expected_doc_type": None,
        "expected_keywords": ["suhu", "hujan", "status"] 
    },
    {
        "id": 6,
        "category": "Trap Question (Anti-Halusinasi)",
        "question": "Berapa jumlah personel pemadam kebakaran di Pontianak tahun 2025?",
        "expected_doc_type": None,
        "expected_keywords": ["tidak disebutkan"] 
    }
]

# ==========================================
# 2. FUNGSI EVALUATOR
# ==========================================
def run_evaluation():
    print("\n" + "="*60)
    print("🏆 EVALUASI RAG KARHUTLA (GOLDEN DATASET + RETRIEVAL TEST)")
    print("="*60)
    print("Memulai pengujian... (Membutuhkan koneksi internet ke API LLM)\n")

    passed = 0
    failed = 0
    total = len(TEST_CASES)
    
    # Dummy context untuk parameter city_context di ask_chatbot
    dummy_city = "Pontianak"

    for test in TEST_CASES:
        print(f"⏳ [TEST {test['id']}] ({test['category']}):")
        print(f"   Pertanyaan: '{test['question']}'")
        
        try:
            # Panggil otak RAG
            answer, doc_context, retrieved_metas = ask_chatbot(test['question'], dummy_city)
            # DEBUGGING
            print(f"   [DEBUG] Jawaban AI: {answer[:200]}...") 
            for meta in retrieved_metas:
                print(f"      - [Dokumen: {meta.get('doc_type')}] Bagian: {meta.get('section', meta.get('term'))}")
            print("\n")
            answer_lower = answer.lower()
            
            # --- UJIAN 1: RETRIEVAL (Apakah ambil dokumen yang benar?) ---
            retrieval_ok = False
            if test['expected_doc_type'] is None:
                retrieval_ok = True
            else:
                for meta in retrieved_metas:
                    if meta.get('doc_type') in test['expected_doc_type']:
                        retrieval_ok = True
                        break
            
            # --- UJIAN 2: GENERATION (Apakah jawaban ada kata kuncinya?) ---
            missing_keywords = []
            for kw in test['expected_keywords']:
                if kw.lower() not in answer_lower:
                    missing_keywords.append(kw)
            
            generation_ok = len(missing_keywords) == 0
            
            # --- HASIL PER TEST ---
            if retrieval_ok and generation_ok:
                print(f"   ✅ PASS: Sumber & Jawaban sesuai.")
                passed += 1
            else:
                print(f"   ❌ FAIL:")
                if not retrieval_ok:
                    print(f"      - Retrieval gagal: Sistem tidak mengambil dokumen {test['expected_doc_type']}.")
                if not generation_ok:
                    print(f"      - Generation gagal: Kata kunci {missing_keywords} tidak ditemukan di jawaban.")
                failed += 1
                
        except Exception as e:
            print(f"   ⚠️ ERROR: Terjadi kesalahan saat tes: {e}")
            failed += 1
            
        print("-" * 60)

    # ==========================================
    # 3. RAPOR & EXIT CODE (Untuk CI/CD)
    # ==========================================
    hit_rate = (passed / total) * 100
    
    print("\n" + "="*60)
    print(f"📊 HASIL AKHIR: {passed}/{total} LULUS (Hit Rate: {hit_rate:.1f}%)")
    
    if failed > 0:
        print("🛑 STATUS: GAGAL. Ada tes yang harus diperbaiki.")
        print("   (Dalam production, proses CI/CD akan dihentikan di sini).")
        sys.exit(1) # EXIT CODE 1 = GAGAL
    else:
        print("🎉 STATUS: SEMPURNA. Sistem RAG siap tempur!")
        sys.exit(0) # EXIT CODE 0 = SUKSES

if __name__ == "__main__":
    run_evaluation()
