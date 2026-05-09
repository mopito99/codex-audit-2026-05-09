import sys
import os
from anthropic import Anthropic

def audit_multiple_files(paths):
    api_key = os.environ.get("ANTHROPIC_API_KEY") or "<REDACTED-BY-CLAUDE-AT-BUNDLE-TIME>"
    client = Anthropic(api_key=api_key)
    
    code_blocks = ""
    for path in paths:
        try:
            with open(path, 'r') as f:
                code_blocks += f"\n\n### Archivo: {path}\n```python\n{f.read()}\n```"
        except Exception as e:
            print(f"Error leyendo {path}: {e}")

    prompt = (
        "Eres el CTO y el Analista de Seguridad Quant principal de un fondo de inversión automatizado. "
        "El sistema que vas a revisar contiene el código en producción (los archivos principales o 'main.py') "
        "de 3 bots de trading distintos de la suite MBOT: Panel, Strategy y Bitunix.\n\n"
        "1) Revisa profundamente la lógica de estos 3 bots.\n"
        "2) Evalúa si están bien codificados en términos de limpieza, manejo de excepciones de API y asincronía.\n"
        "3) Busca intensamente si hay 'fantasmas' (bugs silenciosos, race conditions, leaks de memoria, condiciones de slippage que rompan la simulación) o riesgos escondidos.\n\n"
        "Por favor, entrégame el diagnóstico. No necesitas retornar código arreglado a menos que sea un fallo crítico pequeño. Concéntrate en el DIAGNÓSTICO AUDITOR.\n"
        f"{code_blocks}"
    )
    system = "You are a senior quantitative developer testing bots for hidden bugs."
    
    print(f"🤖 (Gemini) Conectando con la API de Claude para auditar simultáneamente los 3 códigos fuente (Panel, Strategy, Bitunix)...")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    
    result_text = response.content[0].text
    with open('/srv/quantum_ppo/logs/mbot_audit.txt', 'w') as f:
        f.write(result_text)
        
    print(result_text)
    print("\n✅ Auditoría finalizada.")

if __name__ == '__main__':
    bot_paths = [
        "/srv/profitlab_prime/main.py",
        "/srv/bot3_prime/main.py",
        "/srv/bot3_prime_bitunix/main.py"
    ]
    audit_multiple_files(bot_paths)
