Aplicar patch nginx para `/poly/` en inicio.velocityquant.io
=============================================================

El HTML del shadow.html ya está actualizado con la sección τ Polymarket
y JavaScript que pega a `/poly/api/state`. Falta el proxy nginx.

## Comando para aplicar (1 sola línea, lo ejecutas tú)

```bash
sudo cp /etc/nginx/sites-available/inicio.velocityquant.io /etc/nginx/sites-available/inicio.velocityquant.io.bak_pre_poly && \
sudo sed -i '/location \/liquidator\/data\/ {/,/^    }$/{
  /^    }$/a\
\
    # Polymarket Sentiment τ sidecar (V4.1 ponderador) — proxy al FastAPI local\
    location /poly/ {\
        proxy_pass http://127.0.0.1:8090/;\
        proxy_http_version 1.1;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_read_timeout 30s;\
        add_header Cache-Control '"'"'no-cache'"'"' always;\
    }
}' /etc/nginx/sites-available/inicio.velocityquant.io && \
sudo nginx -t && sudo systemctl reload nginx && echo "OK aplicado"
```

## Qué hace

- Backup defensivo del config actual a `.bak_pre_poly`
- Inserta el bloque `location /poly/ { proxy_pass http://127.0.0.1:8090/; ... }` justo después del `location /liquidator/data/`
- `nginx -t` valida sintaxis
- `systemctl reload nginx` aplica sin downtime
- Imprime "OK aplicado" si todo bien

## Verificación post-aplicación

```bash
curl -s https://inicio.velocityquant.io/poly/api/state | python3 -m json.tool | head -10
```

Debe devolver el JSON con `tau_final`, `tau_macro`, `tau_crypto`, etc.

## Después

Refresca https://inicio.velocityquant.io/shadow.html en navegador.
La nueva sección **"polymarket sentiment τ · v4.1 ponderador (gemma 4)"**
aparecerá entre el panel "pyth oracle" y "audit verdicts".

Tooltips con `data-tip` explican cada métrica al pasar el mouse:
- τ_final, τ_crypto, τ_macro, ρ Pearson — definición y aplicación
- Tabla por contrato — fórmulas exactas (ΔProb, VolZ, IV, sigmoide)

## Si quieres rollback

```bash
sudo cp /etc/nginx/sites-available/inicio.velocityquant.io.bak_pre_poly /etc/nginx/sites-available/inicio.velocityquant.io && sudo systemctl reload nginx
```
