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




}