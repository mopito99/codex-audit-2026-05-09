# toxicflow.velocityquant.io — workspace bot toxic flow inversion (Hyperliquid)
# Creado 2026-05-07 · pendiente DNS + certbot --expand antes de habilitar HTTPS

server {
    server_name toxicflow.velocityquant.io;

    root /srv/toxicflow/web;
    index index.html;

    add_header Cache-Control "no-store, no-cache, must-revalidate";

    location / {
        try_files $uri $uri/ =404;
    }

    # API local del bot toxicflow (cuando exista — placeholder por ahora)
    # location /api/ {
    #     proxy_pass http://127.0.0.1:8096/;
    #     proxy_http_version 1.1;
    #     proxy_set_header Host $host;
    #     proxy_set_header X-Real-IP $remote_addr;
    #     proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    #     proxy_set_header X-Forwarded-Proto $scheme;
    #     proxy_read_timeout 30s;
    #     add_header Cache-Control 'no-cache' always;
    # }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/velocityquant.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/velocityquant.io/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = toxicflow.velocityquant.io) {
        return 301 https://$host$request_uri;
    }

    server_name toxicflow.velocityquant.io;
    listen 80;
    return 404;
}
