import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

SIGNAL_FILE = '/srv/quantum_ppo/signals/latest_signal.json'
PORT = 8002

class SignalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Solo respondemos al endpoint validado
        if self.path == '/api/v1/sol_signal':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*') # Permitir lecturas si el panel lo asume por localhost 
            self.end_headers()
            
            if os.path.exists(SIGNAL_FILE):
                try:
                    with open(SIGNAL_FILE, 'r') as f:
                        data = f.read()
                    self.wfile.write(data.encode('utf-8'))
                except Exception as e:
                    error_msg = json.dumps({"error": f"Internal reading error: {str(e)}"})
                    self.wfile.write(error_msg.encode('utf-8'))
            else:
                empty = json.dumps({"error": "No signal generated yet, AI is warming up."})
                self.wfile.write(empty.encode('utf-8'))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found. Use /api/v1/sol_signal"}).encode('utf-8'))

    def log_message(self, format, *args):
        # Solo printear en consola los accesos
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Petición del Panel PHP -> {format%args}")

def run():
    # Bind ESTRICTO a 127.0.0.1 para que sea invisible al mundo exterior e imposible de hachear
    server_address = ('127.0.0.1', PORT)
    httpd = HTTPServer(server_address, SignalHandler)
    print("======================================================")
    print(f"🔌 Micro-API de la Burbuja PPO INICIADA")
    print(f"📡 Escuchando en: http://127.0.0.1:{PORT}/api/v1/sol_signal")
    print("======================================================")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo Micro-API.")
        httpd.server_close()

if __name__ == '__main__':
    run()
