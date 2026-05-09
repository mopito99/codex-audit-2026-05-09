# 05_NGINX_CONFIGS · vhosts producción · snapshot 2026-05-09T07:16:06Z

## /etc/nginx/sites-available/velocityquant.io
```nginx
# VelocityQuant — primary EcoArb domain
# Migración desde hftbots.quantummbo.io (doble-served durante 2-4 semanas)

server {
    server_name velocityquant.io www.velocityquant.io;

    root /home/administrator/hftbots;
    index index.html expenses.html;

    add_header Cache-Control "no-store, no-cache, must-revalidate";

    location / {
        try_files $uri $uri/ =404;
    }

    location /data/ {
        alias /home/administrator/hftbots/data/;
        add_header Cache-Control "no-store, no-cache, must-revalidate";
    }

    location /cyclic/ {
        alias /home/administrator/cyclic/;
        autoindex off;
        types { text/html html; application/json json; text/plain jsonl txt md; }
        default_type text/plain;
        add_header Cache-Control 'no-cache';
    }

    location /liquidator/ {
        alias /home/administrator/liquidator/;
        autoindex off;
        types { text/html html; application/json json; text/plain jsonl txt md; }
        default_type text/plain;
        add_header Cache-Control 'no-cache';
    }

    location /gemma/ {
        alias /home/administrator/gemma/;
        autoindex on;
        autoindex_exact_size off;
        types { text/html html htm; text/plain log txt md jsonl; application/json json; }
        default_type text/plain;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/velocityquant.io/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/velocityquant.io/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot




}


server {
    if ($host = www.velocityquant.io) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    if ($host = velocityquant.io) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    listen 80;
    server_name velocityquant.io www.velocityquant.io;
    return 404; # managed by Certbot




}```

## /etc/nginx/sites-available/inicio.velocityquant.io
```nginx
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


}```

## /etc/nginx/sites-available/toxicflow.velocityquant.io
```nginx
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
```


## sites-enabled symlinks
```
total 20
drwxr-xr-x 2 root root 4096 May  7 16:51 .
drwxr-xr-x 8 root root 4096 May  7 16:50 ..
lrwxrwxrwx 1 root root   43 Apr 23 04:07 ai.cuandeoro.com -> /etc/nginx/sites-available/ai.cuandeoro.com
lrwxrwxrwx 1 root root   43 Apr 22 06:23 ai.quantummbo.io -> /etc/nginx/sites-available/ai.quantummbo.io
lrwxrwxrwx 1 root root   50 Apr 23 04:07 arbitraje.mbottoken.com -> /etc/nginx/sites-available/arbitraje.mbottoken.com
lrwxrwxrwx 1 root root   50 Apr 23 04:07 arbitraje.quantummbo.io -> /etc/nginx/sites-available/arbitraje.quantummbo.io
lrwxrwxrwx 1 root root   45 May  3 02:48 books.cuandeoro.ie -> /etc/nginx/sites-available/books.cuandeoro.ie
lrwxrwxrwx 1 root root   49 Apr 23 04:07 bot2kike.mbottoken.com -> /etc/nginx/sites-available/bot2kike.mbottoken.com
lrwxrwxrwx 1 root root   50 Apr 23 04:07 bot2marco.mbottoken.com -> /etc/nginx/sites-available/bot2marco.mbottoken.com
lrwxrwxrwx 1 root root   49 Apr 23 04:07 bot3fran.mbottoken.com -> /etc/nginx/sites-available/bot3fran.mbottoken.com
lrwxrwxrwx 1 root root   44 Apr 23 04:07 cuandeoro-es.conf -> /etc/nginx/sites-available/cuandeoro-es.conf
lrwxrwxrwx 1 root root   40 Apr 23 04:07 cuandeoro.com -> /etc/nginx/sites-available/cuandeoro.com
lrwxrwxrwx 1 root root   39 Apr 27 16:48 cuandeoro.ie -> /etc/nginx/sites-available/cuandeoro.ie
-rw-r--r-- 1 root root 5724 Apr 23 04:10 cuandeoro.io
lrwxrwxrwx 1 root root   50 Apr 23 04:07 dashboard.cuandeoro.com -> /etc/nginx/sites-available/dashboard.cuandeoro.com
lrwxrwxrwx 1 root root   50 Apr 23 04:07 dashboard.mbottoken.com -> /etc/nginx/sites-available/dashboard.mbottoken.com
lrwxrwxrwx 1 root root   48 Apr 23 04:07 funding.quantummbo.io -> /etc/nginx/sites-available/funding.quantummbo.io
lrwxrwxrwx 1 root root   44 May  1 14:48 git.mbottoken.com -> /etc/nginx/sites-available/git.mbottoken.com
lrwxrwxrwx 1 root root   58 Apr 23 04:07 gravityinvestruiz.mbottoken.com -> /etc/nginx/sites-available/gravityinvestruiz.mbottoken.com
lrwxrwxrwx 1 root root   59 Apr 23 04:07 gravityinvestruiz2.mbottoken.com -> /etc/nginx/sites-available/gravityinvestruiz2.mbottoken.com
lrwxrwxrwx 1 root root   48 Apr 29 12:04 hftbots.quantummbo.io -> /etc/nginx/sites-available/hftbots.quantummbo.io
lrwxrwxrwx 1 root root   50 May  4 11:46 inicio.velocityquant.io -> /etc/nginx/sites-available/inicio.velocityquant.io
lrwxrwxrwx 1 root root   36 Apr 28 21:49 jup-proxy -> /etc/nginx/sites-available/jup-proxy
lrwxrwxrwx 1 root root   52 Apr 23 04:07 kikegravity.mbottoken.com -> /etc/nginx/sites-available/kikegravity.mbottoken.com
lrwxrwxrwx 1 root root   47 Apr 23 04:07 luxbot.mbottoken.com -> /etc/nginx/sites-available/luxbot.mbottoken.com
lrwxrwxrwx 1 root root   47 Apr 23 04:07 luxbot.quantummbo.io -> /etc/nginx/sites-available/luxbot.quantummbo.io
lrwxrwxrwx 1 root root   40 Apr 28 06:15 mbottoken.com -> /etc/nginx/sites-available/mbottoken.com
lrwxrwxrwx 1 root root   45 Apr 30 07:24 movil.mbottoken.io -> /etc/nginx/sites-available/movil.mbottoken.io
lrwxrwxrwx 1 root root   49 Apr 30 14:06 nplatinv.quantummbo.io -> /etc/nginx/sites-available/nplatinv.quantummbo.io
lrwxrwxrwx 1 root root   44 Apr 23 04:07 p2p.cuandeoro.com -> /etc/nginx/sites-available/p2p.cuandeoro.com
lrwxrwxrwx 1 root root   46 Apr 23 04:07 panel.mbottoken.com -> /etc/nginx/sites-available/panel.mbottoken.com
lrwxrwxrwx 1 root root   46 Apr 23 04:07 panel.quantummbo.io -> /etc/nginx/sites-available/panel.quantummbo.io
lrwxrwxrwx 1 root root   52 Apr 23 04:07 panelorobtc.mbottoken.com -> /etc/nginx/sites-available/panelorobtc.mbottoken.com
lrwxrwxrwx 1 root root   49 Apr 23 04:07 panelraw.mbottoken.com -> /etc/nginx/sites-available/panelraw.mbottoken.com
-rw-r--r-- 1 root root 1599 Apr 29 10:23 plsbitunix.mbottoken.com
lrwxrwxrwx 1 root root   51 Apr 23 04:07 plstrategy.mbottoken.com -> /etc/nginx/sites-available/plstrategy.mbottoken.com
lrwxrwxrwx 1 root root   39 Apr 22 10:17 quantum_bots -> /etc/nginx/sites-available/quantum_bots
lrwxrwxrwx 1 root root   42 Apr 23 04:07 realtortoken.es -> /etc/nginx/sites-available/realtortoken.es
lrwxrwxrwx 1 root root   51 Apr 23 04:07 replicator.mbottoken.com -> /etc/nginx/sites-available/replicator.mbottoken.com
lrwxrwxrwx 1 root root   53 May  7 16:51 toxicflow.velocityquant.io -> /etc/nginx/sites-available/toxicflow.velocityquant.io
lrwxrwxrwx 1 root root   54 Apr 23 04:07 tradingbasico.mbottoken.com -> /etc/nginx/sites-available/tradingbasico.mbottoken.com
lrwxrwxrwx 1 root root   44 Apr 23 04:07 tts.quantummbo.io -> /etc/nginx/sites-available/tts.quantummbo.io
lrwxrwxrwx 1 root root   43 May  3 01:05 velocityquant.io -> /etc/nginx/sites-available/velocityquant.io
lrwxrwxrwx 1 root root   42 Apr 23 04:07 wa.cuandeoro.io -> /etc/nginx/sites-available/wa.cuandeoro.io
lrwxrwxrwx 1 root root   47 Apr 23 04:07 webhook.mbottoken.es -> /etc/nginx/sites-available/webhook.mbottoken.es
```
