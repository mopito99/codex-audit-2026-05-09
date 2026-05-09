import os
from anthropic import Anthropic

# Esta es la clase base que usarán tus bots para hablar con Claude
class ClaudeBot:
    def __init__(self, api_key=None, default_model="claude-sonnet-4-6"):
        # Intenta usar la llave provista, o busca la variable local/sistema
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or "<REDACTED-BY-CLAUDE-AT-BUNDLE-TIME>"
        if not self.api_key:
            raise ValueError("Debes proveer una api_key o configurar la variable de entorno ANTHROPIC_API_KEY")
        
        self.client = Anthropic(api_key=self.api_key)
        self.default_model = default_model

    def preguntar(self, prompt, model=None, system_prompt=None):
        """
        Envía un mensaje a Claude. Usa Sonnet por defecto a menos que pases un `model` distinto.
        """
        modelo_a_usar = model if model else self.default_model
        
        # Estructura del mensaje
        kwargs = {
            "model": modelo_a_usar,
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        # Si le quieres dar personalidad o reglas (opcional)
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        
        # Retorna el texto de la respuesta y el uso de tokens para que lleves control
        return {
            "respuesta": response.content[0].text,
            "tokens_entrada": response.usage.input_tokens,
            "tokens_salida": response.usage.output_tokens
        }

# ==========================================
# EJEMPLO DE USO (puedes borrar esto luego)
# ==========================================
if __name__ == "__main__":
    # Pega tu llave API real aquí para probar
    TU_API_KEY = "<REDACTED-PLACEHOLDER>" 
    
    try:
        ia = ClaudeBot(api_key=TU_API_KEY)
        
        print("🤖 Pensando con Sonnet...")
        resultado = ia.preguntar("Dime 3 cosas clave sobre el trading cuántico PPO.")
        
        print("\nResp:", resultado["respuesta"])
        print(f"\n📊 Tokens gastados: {resultado['tokens_entrada']} in / {resultado['tokens_salida']} out")
        
    except Exception as e:
        print(f"Error: {e}")
