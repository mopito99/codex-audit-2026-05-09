#!/usr/bin/env python3
"""
Scraper de Calendario Económico de Investing.com
Corre diariamente a las 6:00 UTC para obtener eventos del día.

Después de que pasa un evento, si mañana es festivo, anuncia cuándo vuelve el mercado.
"""
import os
import sys
import requests
from datetime import datetime, timezone, timedelta
import psycopg2
from urllib.parse import urlparse
import json
import re

# Añadir path del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.config import DATABASE_URL
except ImportError:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:4366037.Cabeza@localhost/profitlab_quantum_db")

# API de Investing.com (endpoint público)
INVESTING_API = "https://sslecal2.investing.com/events/getTodayEvents"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en;q=0.5',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://www.investing.com/economic-calendar/',
}

# Mapeo de países (ID -> nombre)
COUNTRY_ID_MAP = {
    '5': 'United States',
    '4': 'United Kingdom',
    '17': 'Germany',
    '72': 'Germany',  # Eurozone -> Germany
    '35': 'Japan',
    '37': 'China',
    '6': 'Canada',
    '25': 'Australia',
    '12': 'Switzerland',
    '10': 'France',
    '11': 'Italy',
    '26': 'Spain',
}

def get_db_connection():
    """Conectar a PostgreSQL."""
    parsed = urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.path[1:]
    )

def scrape_investing_calendar():
    """Obtener eventos económicos via API de Investing.com."""
    print(f"[{datetime.now(timezone.utc)}] Fetching Investing.com economic calendar...")
    
    today = datetime.now(timezone.utc).date()
    events = []
    
    # Obtener eventos de hoy y próximos 7 días
    for day_offset in range(8):
        target_date = today + timedelta(days=day_offset)
        date_str = target_date.strftime('%Y-%m-%d')
        
        try:
            # Probar endpoint alternativo con scraping de página
            url = f"https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
            params = {
                'country[]': ['5', '4', '17', '72'],  # US, UK, Germany, Eurozone
                'dateFrom': date_str,
                'dateTo': date_str,
                'importance[]': ['2', '3'],  # 2 y 3 estrellas
                'timeZone': '0',  # UTC
                'timeFilter': 'timeRemain',
                'currentTab': 'custom',
                'limit_from': '0',
            }
            
            response = requests.post(url, data=params, headers=HEADERS, timeout=30)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    html_content = data.get('data', '')
                    
                    # Parsear HTML embebido
                    events_from_html = parse_investing_html(html_content, target_date)
                    events.extend(events_from_html)
                except:
                    pass
                    
        except Exception as e:
            print(f"Error fetching {date_str}: {e}")
            continue
    
    # Si el API no funciona, usar datos de ForexFactory como backup
    if not events:
        print("Investing.com API failed, using ForexFactory backup...")
        events = scrape_forexfactory()
    
    print(f"Scraped {len(events)} events")
    return events

def parse_investing_html(html_content, target_date):
    """Parsear HTML embebido de la respuesta de Investing.com."""
    events = []
    
    if not html_content:
        return events
    
    # Regex para extraer eventos
    # Buscar patrones de tiempo, país, evento, impacto
    time_pattern = re.compile(r'<td[^>]*class="[^"]*time[^"]*"[^>]*>([^<]+)</td>')
    event_pattern = re.compile(r'<td[^>]*class="[^"]*event[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>', re.DOTALL)
    
    times = time_pattern.findall(html_content)
    event_names = event_pattern.findall(html_content)
    
    # Contar bulls para impacto
    bulls_pattern = re.compile(r'grayFullBullishIcon|sentiment.*?bull', re.IGNORECASE)
    
    for i, (time_str, event_name) in enumerate(zip(times, event_names)):
        try:
            time_str = time_str.strip()
            event_name = event_name.strip()
            
            if not event_name or len(event_name) < 3:
                continue
            
            # Parsear hora
            event_time = None
            if ':' in time_str:
                try:
                    parts = time_str.split(':')
                    hour, minute = int(parts[0]), int(parts[1][:2])
                    event_time = f"{hour:02d}:{minute:02d}:00"
                except:
                    pass
            
            # Determinar estrellas (por defecto 2 ya que filtramos por importancia)
            stars = 2
            
            events.append({
                'date': target_date,
                'time': event_time,
                'event': event_name[:200],
                'country': 'United States',  # Por defecto US
                'impact': 'high' if stars >= 3 else 'medium',
                'stars': stars,
            })
            
        except Exception as e:
            continue
    
    return events

def scrape_forexfactory():
    """Backup: scrapear ForexFactory."""
    print("Trying ForexFactory as backup...")
    events = []
    
    try:
        url = "https://www.forexfactory.com/calendar"
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            return events
        
        # ForexFactory usa estructura diferente
        # Por ahora retornar vacío si falla
        
    except Exception as e:
        print(f"ForexFactory also failed: {e}")
    
    return events

def save_events_to_db(events):
    """Guardar eventos en la tabla market_calendar."""
    if not events:
        print("No events to save")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    inserted = 0
    updated = 0
    
    for ev in events:
        try:
            # Upsert: insertar o actualizar si ya existe
            cur.execute("""
                INSERT INTO market_calendar (event_date, event_time, event_name, country, impact, stars)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_date, event_name, country) 
                DO UPDATE SET event_time = EXCLUDED.event_time, impact = EXCLUDED.impact, stars = EXCLUDED.stars
                RETURNING (xmax = 0) as inserted
            """, (ev['date'], ev['time'], ev['event'], ev['country'], ev['impact'], ev['stars']))
            
            result = cur.fetchone()
            if result and result[0]:
                inserted += 1
            else:
                updated += 1
                
        except Exception as e:
            print(f"Error saving event {ev['event']}: {e}")
            continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"Saved: {inserted} new, {updated} updated")

def get_next_trading_day():
    """Obtener el próximo día de trading (no festivo, no fin de semana)."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    today = datetime.now(timezone.utc).date()
    check_date = today + timedelta(days=1)
    
    # Buscar festivos de US (mercado principal)
    cur.execute("""
        SELECT event_date FROM market_calendar 
        WHERE impact = 'holiday' AND country = 'United States'
        AND event_date >= %s
        ORDER BY event_date
    """, (today,))
    
    us_holidays = set(row[0] for row in cur.fetchall())
    cur.close()
    conn.close()
    
    # Buscar próximo día hábil
    for _ in range(10):  # Max 10 días
        # Saltar fines de semana
        if check_date.weekday() >= 5:  # Sábado o Domingo
            check_date += timedelta(days=1)
            continue
        # Saltar festivos US
        if check_date in us_holidays:
            check_date += timedelta(days=1)
            continue
        # Encontrado
        return check_date
    
    return check_date

def update_market_status_message():
    """Actualizar mensaje de estado del mercado después de eventos."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    now = datetime.now(timezone.utc)
    today = now.date()
    
    # Verificar si mañana es festivo
    tomorrow = today + timedelta(days=1)
    cur.execute("""
        SELECT event_name, country FROM market_calendar 
        WHERE event_date = %s AND impact = 'holiday' AND country = 'United States'
        LIMIT 1
    """, (tomorrow,))
    
    holiday_tomorrow = cur.fetchone()
    
    if holiday_tomorrow:
        next_trading = get_next_trading_day()
        message = f"📅 Mañana festivo: {holiday_tomorrow[0]}. Mercado vuelve: {next_trading.strftime('%d %b %Y')}"
        print(message)
        
        # Podrías guardar esto en una tabla de estado o enviarlo a un webhook
        # Por ahora solo log
    
    cur.close()
    conn.close()

def cleanup_old_events():
    """Limpiar eventos antiguos (más de 30 días)."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
    
    cur.execute("""
        DELETE FROM market_calendar 
        WHERE event_date < %s AND impact != 'holiday'
    """, (cutoff,))
    
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    
    if deleted > 0:
        print(f"Cleaned up {deleted} old events")

def main():
    """Función principal."""
    print(f"\n{'='*60}")
    print(f"Economic Calendar Scraper - {datetime.now(timezone.utc)}")
    print(f"{'='*60}\n")
    
    # 1. Scrapear eventos
    events = scrape_investing_calendar()
    
    # 2. Guardar en DB
    save_events_to_db(events)
    
    # 3. Verificar estado del mercado (festivos mañana)
    update_market_status_message()
    
    # 4. Limpiar eventos viejos
    cleanup_old_events()
    
    print(f"\n{'='*60}")
    print("Done!")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
