# Jetson Orin Nano — Web Viewer Server Setup

The Jetson is configured to serve the web-viewer over a local WiFi hotspot with no login required. Everything starts automatically on boot.

---

## What's Running

| Service | Details |
|---|---|
| **nginx** | Serves the web-viewer at `http://10.42.0.1` |
| **WiFi Hotspot** | SSID: `Jetson` / Password: `jetson01` / Interface: `wlP1p1s0` |

Both are system-level services that start at boot before any user logs in.

---

## Boot Sequence

1. Jetson powers on
2. NetworkManager brings up the `Jetson` WiFi hotspot
3. nginx starts and serves the web-viewer

No login required.

---

## Connecting

1. Connect a device to the `Jetson` WiFi network (password: `jetson01`)
2. Open a browser and navigate to `http://10.42.0.1`

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

> **Note:** nvm must be loaded for `npm` to use Node 20. If the command fails, run:
> ```bash
> export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
> ```
> Then retry the build.

### Add a new recording

Drop the files into `web-viewer/public/recordings/<recording-id>/` and add an entry to `manifest.json`. No rebuild needed.

### Change the hotspot SSID or password

```bash
sudo nmcli connection modify "Hotspot" 802-11-wireless.ssid "NewName"
sudo nmcli connection modify "Hotspot" 802-11-wireless-security.psk "NewPassword"
sudo nmcli connection down "Hotspot" && sudo nmcli connection up "Hotspot"
```

---

## nginx Config

Located at `/etc/nginx/sites-available/web-viewer`:

```nginx
server {
    listen 80;
    server_name _;

    root /home/eyesof/workspace/InTheEyesOf/web-viewer/dist;
    index index.html;

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
