import feedparser
import json
import os
import argparse
from datetime import datetime
from claude_client import ClaudeBot

def fetch_news():
    urls = [
        ("Cointelegraph", "https://cointelegraph.com/rss"),
        ("Investing.com", "https://www.investing.com/rss/news_301.rss")
    ]
    
    news_items = []
    
    for source, url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]: # Tomar las últimas 8 de cada fuente
                news_items.append(f"Fuente: {source} | Titular: {entry.title}")
        except Exception as e:
            print(f"Error fetching from {source}: {e}")
            
    return "\n".join(news_items)

def analyze_market_sentiment(news_text):
    bot = ClaudeBot() # Toma ANTHROPIC_API_KEY del enviroment
    
    system_prompt = """Eres el CTO y Analista Financiero Senior de un fondo de alto riesgo cripto. 
Tu trabajo es leer titulares de noticias recientes sobre macroeconomía, cripto y geopolítica y emitir un veredicto frío, lógico y calculador del sentimiento predominante del mercado.
Debes sacar una calificación 'macro_score' del 0 al 100.
0 = Pánico Absoluto y Caída Libre (Extremadamente Bearish)
50 = Mercados Laterales / Neutral
100 = Euforia y Crecimiento Fuerte (Extremadamente Bullish)

Responde EXCLUSIVAMENTE con un JSON válido con este formato:
{
  "macro_score": 50,
  "fundamental_summary": "Resumen de un párrafo sobre la situación macroeconómica y geopolítica justificando el score."
}
No agregues texto fuera del JSON."""

    prompt = f"TITULARES DE LA MAÑANA:\n{news_text}\n\nGenera tu análisis JSON ahora."
    
    print("🧠 Claude Sonnet analizando titulares...")
    result = bot.preguntar(prompt, system_prompt=system_prompt)
    
    resp = result['respuesta']
    
    try:
        if "```json" in resp:
            resp = resp.split("```json")[1].split("```")[0]
        elif "```" in resp:
            resp = resp.split("```")[1].split("```")[0]
        
        parsed = json.loads(resp.strip())
        parsed['timestamp'] = datetime.utcnow().isoformat()
        parsed['tokens_usados'] = result['tokens_entrada'] + result['tokens_salida']
        return parsed
    except Exception as e:
        print(f"Error parseando la respuesta de Claude: {e}")
        print("Respuesta cruda:", resp)
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Guardar el resultado en signals/macro_sentiment.json")
    args = parser.parse_args()

    print("📰 Extrayendo noticias geopolíticas y fundamentales...")
    news_text = fetch_news()
    
    if not news_text:
        print("No se pudieron extraer noticias.")
        return
        
    analysis_data = analyze_market_sentiment(news_text)
    
    if analysis_data:
        print("\n===========================================")
        print("📊 BRIEFING MATUTINO DE CLAUDE (CTO)")
        print("===========================================")
        print(f"🔹 SCORE MACRO (0-100): {analysis_data['macro_score']}")
        print(f"🔹 ANÁLISIS FUNDAMENTAL:")
        print(f"   {analysis_data['fundamental_summary']}")
        print("===========================================")
        print(f"Coste en tokens para este análisis: {analysis_data.get('tokens_usados', 'N/A')}\n")
        
        if args.save:
            os.makedirs('/srv/quantum_ppo/signals', exist_ok=True)
            path = '/srv/quantum_ppo/signals/macro_sentiment.json'
            with open(path, 'w') as f:
                json.dump(analysis_data, f, indent=4)
            print(f"✅ Veredicto guardado silenciosamente en {path}")

if __name__ == "__main__":
    main()
