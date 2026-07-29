#!/usr/bin/env bash
# Apply HTTPS to the nginx web-viewer config and rebuild the web-viewer.
# Run once: bash scripts/enable_https.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOTSPOT_IP="10.42.0.1"
NGINX_SITE="/etc/nginx/sites-available/web-viewer"

echo "=== Step 1: Generate self-signed TLS certificate ==="
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/web-viewer.key \
    -out /etc/ssl/certs/web-viewer.crt \
    -subj "/CN=$HOTSPOT_IP" \
    -addext "subjectAltName=IP:$HOTSPOT_IP"
echo "Certificate written."

echo "=== Step 2: Update nginx config ==="
sudo tee "$NGINX_SITE" > /dev/null <<NGINX
server {
    listen 80;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/ssl/certs/web-viewer.crt;
    ssl_certificate_key /etc/ssl/private/web-viewer.key;

    root $REPO_DIR/web-viewer/dist;
    index index.html;

    location = /web-viewer.crt {
        alias /etc/ssl/certs/web-viewer.crt;
        default_type application/x-x509-ca-cert;
    }

    location /recordings/ {
        alias $REPO_DIR/web-viewer/public/recordings/;
        autoindex off;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX

sudo nginx -t
sudo systemctl restart nginx
echo "nginx restarted with HTTPS."

echo "=== Step 3: Build web-viewer ==="
cd "$REPO_DIR/web-viewer"
npm run build
echo "Build complete."

echo ""
echo "=== Done ==="
echo "  Open browser:  https://$HOTSPOT_IP"
echo "  Install cert:  https://$HOTSPOT_IP/web-viewer.crt  (once per device)"
