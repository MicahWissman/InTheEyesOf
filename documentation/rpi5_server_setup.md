# Raspberry Pi 5 — Web Viewer Server Setup

The Pi is configured to serve the web-viewer over a local WiFi hotspot with no login required. Everything starts automatically on boot.

---

## What's Running

| Service | Details |
|---|---|
| **nginx** | Serves the web-viewer at `https://10.42.0.1` (HTTP redirects to HTTPS) |
| **WiFi Hotspot** | SSID: `InTheEyesOf` / Password: `jetson01` / Interface: `wlan0` |

Both are system-level services that start at boot before any user logs in.

---

## Initial Setup

Run these two scripts in order from the repo root:

```bash
bash scripts/setup_rpi5_server.sh
bash scripts/enable_https.sh
```

`setup_rpi5_server.sh`:
1. Installs nginx and ensures NetworkManager is present
2. Builds the web-viewer (`npm ci && npm run build`)
3. Writes the nginx config and enables the site
4. Creates and activates the `InTheEyesOf` WiFi hotspot

`enable_https.sh`:
1. Generates a self-signed TLS certificate for `10.42.0.1`
2. Updates the nginx config to serve HTTPS on port 443 and redirect HTTP → HTTPS
3. Rebuilds the web-viewer

> **After running `enable_https.sh`**, install the cert on each device once — see [HTTPS Setup](#https-setup-required-for-gps-on-mobile) below.

> **Prerequisite:** Raspberry Pi OS (Bookworm recommended) with NetworkManager managing networking. Confirm with `nmcli device status` — if `wlan0` is listed, you're ready.

---

## Boot Sequence

1. Pi powers on
2. NetworkManager brings up the `InTheEyesOf` WiFi hotspot
3. nginx starts and serves the web-viewer

No login required.

---

## Connecting

1. Connect a device to the `InTheEyesOf` WiFi network (password: `jetson01`)
2. Install the TLS cert on the device (first time only — see [HTTPS Setup](#https-setup-required-for-gps-on-mobile))
3. Open a browser and navigate to `https://10.42.0.1`

---

## File Layout

```
web-viewer/
├── dist/              ← built app, served by nginx at /
└── public/
    └── recordings/    ← data files, served by nginx at /recordings/
        ├── manifest.json
        ├── gilbert-test-2/
        │   ├── narrative_anchors.json
        │   ├── pointcloud.ply
        │   └── semantic_graph.json
        └── gilbert-test-3/
            ├── narrative_anchors.json
            ├── pointcloud.ply
            └── semantic_graph.json
```

Data files in `public/recordings/` are served directly — they are never copied into `dist/` on rebuild.

---

## Day-to-Day Operations

### Update the web-viewer UI

```bash
cd /home/eyesof/workspace/InTheEyesOf/web-viewer
npm run build
```

nginx picks up `dist/` immediately — no restart needed.

### Add a new recording

Drop the files into `web-viewer/public/recordings/<recording-id>/` and add an entry to `manifest.json`. No rebuild needed.

### Change the hotspot SSID or password

```bash
sudo nmcli connection modify "InTheEyesOf" 802-11-wireless.ssid "NewName"
sudo nmcli connection modify "InTheEyesOf" 802-11-wireless-security.psk "NewPassword"
sudo nmcli connection down "InTheEyesOf" && sudo nmcli connection up "InTheEyesOf"
```

---

## HTTPS Setup (required for GPS on mobile)

Browsers block the Geolocation API on plain HTTP. Run once:

```bash
bash scripts/enable_https.sh
```

**Trusting the cert on each device (once per device):**

The cert is served directly by nginx for easy installation.

- **iOS:** Open `https://10.42.0.1/web-viewer.crt` in Safari → allow download → Settings → General → VPN & Device Management → tap the profile → Install → then Settings → General → About → Certificate Trust Settings → enable full trust
- **Android:** Open `https://10.42.0.1/web-viewer.crt` → download → Settings → Security → Install certificate → CA Certificate

After trusting, navigate to `https://10.42.0.1` — GPS will be available.

---

## nginx Config

Located at `/etc/nginx/sites-available/web-viewer`:

```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/ssl/certs/web-viewer.crt;
    ssl_certificate_key /etc/ssl/private/web-viewer.key;

    root /home/eyesof/workspace/InTheEyesOf/web-viewer/dist;
    index index.html;

    # Serve the cert for easy device installation
    location = /web-viewer.crt {
        alias /etc/ssl/certs/web-viewer.crt;
        default_type application/x-x509-ca-cert;
    }

    location /recordings/ {
        alias /home/eyesof/workspace/InTheEyesOf/web-viewer/public/recordings/;
        autoindex off;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### Useful commands

```bash
sudo systemctl status nginx       # check if running
sudo systemctl restart nginx      # restart
sudo nginx -t                     # validate config before restarting
```

---

## Differences from Jetson Setup

| | Jetson Orin Nano | Raspberry Pi 5 |
|---|---|---|
| WiFi interface | `wlP1p1s0` | `wlan0` |
| Hotspot SSID | `Jetson` | `InTheEyesOf` |
| Node.js | via nvm | system package |
| Hotspot connection name | `Hotspot` | `InTheEyesOf` |
