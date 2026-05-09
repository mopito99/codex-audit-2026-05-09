import requests
from bs4 import BeautifulSoup
import pandas as pd


def get_crypto_fundamentals():
    """
    Fetch crypto economic events from Investing.com.
    Returns a dict with either today's events or the next upcoming important event.
    """
    try:
        # Crypto events, timeZone=58 (Madrid), lang=1 (English)
        url = "https://sslecal2.forexprostools.com?columns=exc_time,exc_currency,exc_importance,exc_event&category=_crypto&calType=week&timeZone=58&lang=1"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.content, 'html.parser')
        
        events = []
        current_date_obj = None
        
        rows = soup.select('table#data_table tr')
        for row in rows:
            if 'theDay' in row.get('class', []):
                date_text = row.get_text(strip=True)
                try:
                    current_date_obj = pd.to_datetime(date_text).date()
                except:
                    current_date_obj = None
                continue
            
            if 'eventRow' in row.get('class', []) and current_date_obj:
                time_cell = row.select_one('.time')
                event_cell = row.select_one('.event')
                sentiment_icons = row.select('.sentiment i.grayFullBullishIcon')
                
                if time_cell and event_cell:
                    impact = len(sentiment_icons)
                    events.append({
                        'date': current_date_obj,
                        'time': time_cell.get_text(strip=True),
                        'event': event_cell.get_text(strip=True),
                        'impact': impact
                    })
        
        try:
            today = pd.Timestamp.now(tz='Europe/Madrid').date()
        except:
            today = pd.Timestamp.now().date()
        
        future_events_all = [e for e in events if e['date'] >= today]
        
        if not future_events_all:
            return {'type': 'none', 'message': 'No crypto events found'}
        
        has_high = any(e['impact'] == 3 for e in future_events_all)
        target_impact = 3 if has_high else max(e['impact'] for e in future_events_all)
        
        important_events = [e for e in future_events_all if e['impact'] >= target_impact]
        todays_events = [e for e in important_events if e['date'] == today]
        
        if todays_events:
            return {
                'type': 'today',
                'date': str(today),
                'impact': target_impact,
                'events': [{'time': e['time'], 'event': e['event']} for e in todays_events]
            }
        else:
            upcoming = [e for e in important_events if e['date'] > today]
            if upcoming:
                next_event = upcoming[0]
                return {
                    'type': 'upcoming',
                    'date': str(next_event['date']),
                    'time': next_event['time'],
                    'event': next_event['event'],
                    'impact': next_event['impact']
                }
            else:
                return {'type': 'none', 'message': 'No upcoming crypto events'}
    
    except Exception as e:
        return {'type': 'error', 'message': str(e)}
