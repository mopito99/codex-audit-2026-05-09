# inicio.velocityquant.io — entry portal del proyecto VelocityQuant
# Sirve el index unificado del stack (liquidator dashboards).

server {
    server_name inicio.velocityquant.io;

    root /home/administrator/liquidator;
    index index.html;

    add_header Cache-Control "no-store, no-cache, must-revalidate";

    location / {
        try_files $uri $uri/ =404;
    }

    location /data/ {
        alias /home/administrator/liquidator/data/;
        types { text/html html; application/json json; text/plain jsonl txt md; }
        default_type text/plain;
        add_header Cache-Control 'no-cache';
    }

    location /liquidator/data/ {
        alias /home/administrator/liquidator/data/;
        types { text/html html; application/json json; text/plain jsonl txt md; }
        default_type text/plain;
        add_header Cache-Control 'no-cache';
    }

    # Polymarket Sentiment τ sidecar (V4.1 ponderador) — proxy al FastAPI local

    location /debate/ {
        proxy_pass http://127.0.0.1:8095/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        client_max_body_size 60M;
        add_header Cache-Control 'no-cache' always;
    }

    location /poly/api/ {
        # [r152-M2] auth_basic bundled · firmado Gemma · Codex C-04
        auth_basic "VelocityQuant Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd_vq;

        proxy_pass http://127.0.0.1:8090/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        add_header Cache-Control 'no-cache' always;
    }

    location /poly/ {
        proxy_pass http://127.0.0.1:8090/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        add_header Cache-Control 'no-cache' always;
    }


    # NFP Audit Dashboard (firma Gemma r110 §4 + r111 §5: Basic Auth + rate limit)
    # Rate limit zone definida en nginx.conf principal con limit_req_zone
    location /poly/audit/ {
        limit_req zone=audit_dashboard burst=15 nodelay;
        # [r152-M1] auth_basic restored · firmado Gemma · Codex C-04/C-05 fix
        auth_basic "VelocityQuant Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd_vq;


        proxy_pass http://127.0.0.1:8090/audit/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        add_header Cache-Control 'no-cache' always;
    }


    # PNL Dashboard (balance Solana RPC + SHADOW would-profit summary)
    location /poly/pnl/ {
        limit_req zone=audit_dashboard burst=15 nodelay;
        # [r152-M1] auth_basic restored · firmado Gemma · Codex C-04/C-05 fix
        auth_basic "VelocityQuant Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd_vq;


        proxy_pass http://127.0.0.1:8090/pnl/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        add_header Cache-Control 'no-cache' always;
    }


    # Informe ejecutivo Fran (creado 2026-05-08 14:10 UTC)
    location /fran/ {
        alias /srv/status_fran/web/;
        index index.html;
        try_files $uri $uri/ /index.html =404;
        add_header Cache-Control 'no-store, no-cache, must-revalidate' always;
    }


    # Codex dropbox · informe técnico tar (creado 2026-05-08 14:30 UTC)
    location /codex/ {
        alias /srv/codex_dropbox/;
        autoindex on;
        autoindex_format html;
        add_header Cache-Control 'no-store, no-cache, must-revalidate' always;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/velocityquant.io/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/velocityquant.io/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}


server {
    if ($host = inicio.velocityquant.io) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    server_name inicio.velocityquant.io;

    listen 80;
    return 404; # managed by Certbot


}