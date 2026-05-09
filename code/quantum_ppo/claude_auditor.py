import sys
import os
from anthropic import Anthropic

def audit_file(filepath):
    api_key = os.environ.get("ANTHROPIC_API_KEY") or "<REDACTED-BY-CLAUDE-AT-BUNDLE-TIME>"
    client = Anthropic(api_key=api_key)
    
    with open(filepath, 'r') as f:
        code = f.read()
    
    prompt = (
        "Por favor, revisa el siguiente script Python de nuestro sistema de Trading con PPO en la red de pruebas. "
        "Audita su arquitectura matemática y evalúa y corrige lo que se necesite. "
        "Dime por qué y bríndame EL SCRIPT NUEVO y REPROGRAMADO POR TI."
        f"\n\n```python\n{code}\n```"
    )
    system = "You are the Lead Quantitative Developer and CTO. Return raw feedback and the optimized python code blocks."
    
    print(f"🤖 (Gemini) Conectando directamente con la API de Claude para que audite y reprograme '{filepath}'...")
    print("-----------------------------------------------------------------------------------------------------")
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    
    result_text = response.content[0].text
    with open('/srv/quantum_ppo/logs/claude_audit.txt', 'w') as f:
        f.write(result_text)
        
    print(result_text)
    print("-----------------------------------------------------------------------------------------------------")
    print("✅ (Gemini) Respuesta de Claude recibida y guardada en '/srv/quantum_ppo/logs/claude_audit.txt'")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        audit_file(sys.argv[1])
    else:
        print("Error: Provee la ruta del script a auditar.")
