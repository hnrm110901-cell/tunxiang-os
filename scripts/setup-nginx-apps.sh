#!/bin/bash
# 生成 Nginx 前端应用配置
SSL_CERT="/etc/letsencrypt/live/tunxiangos.com/fullchain.pem"
SSL_KEY="/etc/letsencrypt/live/tunxiangos.com/privkey.pem"

cat > /etc/nginx/sites-available/tunxiangos-apps << NGINX
server {
    listen 443 ssl;
    server_name os.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/os;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
server {
    listen 443 ssl;
    server_name pos.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/pos;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
server {
    listen 443 ssl;
    server_name hub.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/hub;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
server {
    listen 443 ssl;
    server_name forge.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/forge;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
server {
    listen 443 ssl;
    server_name kds.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/kds;
    index index.html;
    location / { try_files \$uri \$uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
    location /ws/ { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade"; }
}
server {
    listen 443 ssl;
    server_name m.tunxiangos.com;
    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    root /var/www/m;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
}
NGINX

ln -sf /etc/nginx/sites-available/tunxiangos-apps /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "Done! Nginx configured for 6 frontend apps."
