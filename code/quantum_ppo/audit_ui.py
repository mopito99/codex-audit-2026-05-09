import sys
import os
sys.path.append("/srv/quantum_ppo")
from claude_client import ClaudeBot

def run_audit():
    prompt = """
    Eres el CTO Senior de una empresa de trading algorítmico.
    Tus desarrolladores te pidieron auditar la página de "Estrategias" de tu Bot de Trading.
    
    Descubrimos que en el Frontend (bot3_prime/web/templates/strategies.html), el usuario ve los siguientes campos para configurar:
    
    - max_margin: "Margen máximo por trade"
    - lr_timeout_h y lr_timeout_enabled: "Cierre automático por tiempo LR"
    - tp_monitor_enabled: "Monitor de TP en tiempo real"
    - reversal_enabled: "Detección de reversal BTC"
    - cme_close_enabled: "Cierre CME fin de semana"
    - max_age_enabled y max_age_h: "Cierre por edad máxima"
    - reconcile_enabled: "Reconciliación automática BingX"
    - only_plus: "Solo señales Plus"
    - tp1_close_pct y tp2_close_pct: "% posición que cierra en TP1/TP2"
    - lev_normal y lev_strong: "Apalancamiento"
    
    El frontend envía TODO esto a la ruta /api/risk-config (POST) mediante JSON.
    Sin embargo, al ver la base de datos (models.Settings) y la ruta en main.py que lo procesa:

    ```python
    @app.post("/api/risk-config")
    async def update_risk_config(request: Request):
        body = await request.json()
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Settings).limit(1))
            s = result.scalar_one_or_none()
            if not s:
                s = Settings(); session.add(s)
            if "max_margin" in body: s.max_margin = max(0.0, float(body["max_margin"]))
            if "tp1_be_pct" in body: s.tp1_be_pct = max(0.0, min(100.0, float(body["tp1_be_pct"])))
            if "tp2_ts_pct" in body: s.tp2_ts_pct = max(0.0, min(100.0, float(body["tp2_ts_pct"])))
            if "only_plus" in body and hasattr(s,"only_plus_signals"): s.only_plus_signals = bool(body["only_plus"])
            if "tp1_close_pct" in body and hasattr(s,"tp1_close_pct"): s.tp1_close_pct = max(1, min(99, int(body["tp1_close_pct"])))
            if "tp2_close_pct" in body and hasattr(s,"tp2_close_pct"): s.tp2_close_pct = max(1, min(99, int(body["tp2_close_pct"])))
            if "lev_normal" in body and hasattr(s,"leverage_normal"): s.leverage_normal = max(1, min(20, int(body["lev_normal"])))
            if "lev_strong" in body and hasattr(s,"leverage_strong"): s.leverage_strong = max(1, min(20, int(body["lev_strong"])))
            await session.commit()
        return {"status": "ok"}
    ```

    Base de Datos Settings Relevante (models.py):
    ```python
    max_margin = Column(Float, default=50.0)
    tp1_be_pct = Column(Float, default=50.0)
    tp2_ts_pct = Column(Float, default=50.0)
    only_plus_signals = Column(Boolean, default=False)
    tp1_close_pct = Column(Integer, default=30)
    tp2_close_pct = Column(Integer, default=60)
    leverage_normal = Column(Integer, default=7)
    leverage_strong = Column(Integer, default=10)
    ```

    Genera una auditoría severa de 3 puntos clave destacando:
    1. Qué parámetros son falsos (ghost parameters) porque el frontend los envía pero la DB y el backend los tiran a la basura sin guardarlos.
    2. Consecuencias graves para el usuario que manipula botones en la UI y ve "Guardado" pero el bot no hace caso.
    3. Solución Arquitectónica recomendada a inyectar en models.py y main.py.
    """
    
    bot = ClaudeBot(default_model="claude-3-5-sonnet-20241022")
    res = bot.preguntar(prompt)
    
    with open("/srv/quantum_ppo/logs/ui_audit_result.txt", "w") as f:
        f.write(res["respuesta"])

if __name__ == "__main__":
    run_audit()
