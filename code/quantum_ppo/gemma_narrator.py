import os
import time
import requests
import json
from datetime import datetime

REPORT_PATH = "/srv/quantum_ppo/logs/report_latest.txt"
NARRATOR_LOG_PATH = "/srv/quantum_ppo/logs/gemma_narracion.txt"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma4:31b"
INTERVAL_SECONDS = 600  # 10 minutes

def read_latest_report():
    if not os.path.exists(REPORT_PATH):
        return None
    with open(REPORT_PATH, 'r', encoding='utf-8') as f:
        return f.read()

def generate_commentary(report_text):
    prompt = f"""
Eres "Gemma", la comentarista técnica y amena del servidor de Inteligencia Artificial A100.
Tu trabajo es explicar qué está haciendo actualmente nuestra otra IA (un bot de Reinforcement Learning PPO) que está aprendiendo a hacer trading en futuros de SOL/USDT.
El bot comenzó perdiendo (modo bebé) porque el entorno lo castiga severamente por malas decisiones, pero aprenderá a sobrevivir y ganar con el paso de iteraciones de millones de velas.

Aquí están las métricas reales recientes del sistema:

{report_text}

Tu estilo debe ser como un comentarista analítico pero muy entretenido, coloquial y directo. 
Explícame a grandes rasgos:
1. ¿A qué velocidad va el entrenamiento y cómo va progresando?
2. La supervivencia del episodio (ep_len_mean) y cómo la entiendes.
3. Lo saludable del entorno (Entropy, Rewards).
No resumas simplemente los números; DÁLES SIGNIFICADO con lenguaje muy natural y entusiasta en español.
Escríbelo en 2 o 3 párrafos como máximo.
"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "Sin respuesta de Gemma.")
    except Exception as e:
        return f"Oops! Error de conexión con Ollama: {str(e)}"

def main():
    print(f"🚀 Narrador Gemma4:31b Iniciado. Esperando reporte en {REPORT_PATH}...")
    last_report_content = ""
    
    while True:
        report = read_latest_report()
        
        if report and report != last_report_content:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now_str}] 📢 Nuevo reporte detectado. Consultando a Gemma4...")
            
            comentario = generate_commentary(report)
            
            output = f"══════════════════════════════════════════════════════════\n"
            output += f"🎙️ REPORTE NARRADO DE GEMMA4 — {now_str}\n"
            output += f"══════════════════════════════════════════════════════════\n"
            output += f"{comentario}\n\n"
            
            with open(NARRATOR_LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(output)
                
            print(f"[{now_str}] ✅ Comentario guardado en log.")
            last_report_content = report
            
        time.sleep(60) # Revisar cada minuto si hay cambios en el reporte (que cambia cada 10m)

if __name__ == '__main__':
    main()
