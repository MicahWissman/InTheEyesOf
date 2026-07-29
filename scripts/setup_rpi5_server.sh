#!/usr/bin/env bash
# Raspberry Pi 5 server setup — mirrors Jetson server config.
# Run once as the eyesof user (sudo access required).
# Usage: bash scripts/setup_rpi5_server.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WIFI_IFACE="wlan0"
HOTSPOT_SSID="InTheEyesOf"
HOTSPOT_PASSWORD="jetson01"
HOTSPOT_IP="10.42.0.1"
NGINX_SITE="/etc/nginx/sites-available/web-viewer"
NGINX_ENABLED="/etc/nginx/sites-enabled/web-viewer"

echo "=== Step 1: Install dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y nginx network-manager nodejs npm

echo "=== Step 2: Build the web-viewer ==="
cd "$REPO_DIR/web-viewer"
npm ci
npm run build
cd "$REPO_DIR"

echo "=== Step 3: Grant nginx traversal access to home directory ==="
# nginx runs as www-data and needs execute (traverse) permission on each directory
# in the path to reach the repo. This does NOT expose home directory contents.
chmod o+x "$HOME"

echo "=== Step 4: Generate self-signed TLS certificate ==="
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/web-viewer.key \
    -out /etc/ssl/certs/web-viewer.crt \
    -subj "/CN=$HOTSPOT_IP" \
    -addext "subjectAltName=IP:$HOTSPOT_IP"
echo "Certificate written."

echo "=== Step 5: Write nginx config (HTTP → HTTPS redirect + TLS) ==="
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

    # Serve the cert so devices can install it easily
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

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf "$NGINX_SITE" "$NGINX_ENABLED"
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
echo "nginx configured and running."

echo "=== Step 6: Create WiFi hotspot ==="
# Remove existing connection of same name if present
sudo nmcli connection delete "$HOTSPOT_SSID" 2>/dev/null || true

sudo nmcli connection add \
    type wifi \
    ifname "$WIFI_IFACE" \
    con-name "$HOTSPOT_SSID" \
    autoconnect yes \
    ssid "$HOTSPOT_SSID" \
    -- \
    wifi.mode ap \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$HOTSPOT_PASSWORD" \
    ipv4.method shared \
    ipv4.addresses "$HOTSPOT_IP/24"

sudo nmcli connection up "$HOTSPOT_SSID"
echo "Hotspot '$HOTSPOT_SSID' is up on $WIFI_IFACE."

echo ""
echo "=== Setup complete ==="
echo "  Connect to WiFi:  $HOTSPOT_SSID  (password: $HOTSPOT_PASSWORD)"
echo "  Open browser:     https://$HOTSPOT_IP"
echo "  Install cert:     https://$HOTSPOT_IP/web-viewer.crt  (once per device)"
