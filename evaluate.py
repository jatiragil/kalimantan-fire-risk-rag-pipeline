import sys
import os
from dotenv import load_dotenv

# Tambahkan path agar bisa import dari dashboard
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dashboard.app import ask_chatbot

load_dotenv()

def run_evaluation():
    print("="*50)
    print("MEMULAI EVALUASI CHATBOT KARHUTLA")
    print("="*50)
    
    city = "Banjarmasin"

    # 1. Uji Data Cuaca (Forecast)
    print("\n[1] Uji Data Cuaca: 'Bagaimana cuaca besok?'")
    ans, _ = ask_chatbot("Bagaimana cuaca besok?", city)
    print(f"Jawaban AI:\n{ans[:300]}...\n")
    
    # 2. Uji Dokumen (Pengetahuan)
    print("\n[2] Uji Dokumen: 'Apa itu FFMC dan mengapa penting?'")
    ans, _ = ask_chatbot("Apa itu FFMC dan mengapa penting?", city)
    print(f"Jawaban AI:\n{ans[:300]}...\n")
    
    # 3. Uji Guardrail (Out-of-Scope)
    print("\n[3] Uji Guardrail: 'Siapa presiden Indonesia?'")
    ans, _ = ask_chatbot("Siapa presiden Indonesia?", city)
    print(f"Jawaban AI:\n{ans}\n")

    print("="*50)
    print("EVALUASI SELESAI")
    print("="*50)

if __name__ == "__main__":
    run_evaluation()
