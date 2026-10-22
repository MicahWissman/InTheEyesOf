# Raspberry Pi 5 hotspot + web viewer setup

This file tells Claude Code how to turn a Raspberry Pi 5 into a standalone Wi-Fi
hotspot that serves the InTheEyesOf web viewer (`npm run dev` in `web-viewer/`)
to phones, tablets and laptops that join its network. It is a port of the setup
already working on the Jetson (`InTheEyesOf-Jetson`, 10.42.0.1).

## There are TWO Pis, and their networks must differ

The same instructions run on two separate Pi 5 units, often switched on next to
each other. **Each Pi broadcasts its own network with its own SSID, subnet and
hostname. Never configure both Pis with the same values.** Matching SSIDs make
clients roam between the two Pis at random, and matching subnets make it
impossible to tell which Pi a device is talking to.

| Setting                  | Pi 1                      | Pi 2                      |
|--------------------------|---------------------------|---------------------------|
| Hostname                 | `duo-pi-1`                | `duo-pi-2`                |
| Wi-Fi SSID               | `duo-pi-1`                | `duo-pi-2`                |
| Wi-Fi password (WPA2)    | `intheeyesof`             | `intheeyesof`             |
| Hotspot IP (gateway)     | `10.42.1.1/24`            | `10.42.2.1/24`            |
| Wi-Fi channel (2.4 GHz)  | `1`                       | `11`                      |
| NetworkManager profile   | `duo-pi-hotspot`          | `duo-pi-hotspot`          |
| Web viewer URL           | `https://10.42.1.1:5173`  | `https://10.42.2.1:5173`  |
| GPS relay                | `ws://10.42.1.1:8080`     | `ws://10.42.2.1:8080`     |

The password is the same as on the Jetson hotspot, on purpose. Channels 1 and 11
don't overlap, so the two Pis don't interfere with each other when side by side.

### Step 0: work out which Pi this is

1. Run `hostname`. If it prints `duo-pi-1` or `duo-pi-2`, use that column.
2. Otherwise **ask the user** which unit this is (1 or 2). Never guess, and never
   default to Pi 1. If the other Pi is already set up, run `nmcli -f SSID dev wifi`
   and confirm its SSID shows up, so you don't pick the same identity twice.
3. Set the hostname so the identity survives future sessions:
   `sudo hostnamectl set-hostname duo-pi-N`, and update the `127.0.1.1` line in
   `/etc/hosts` to match.

Use the values from that column for every step below.

## Platform facts (Pi 5 vs. Jetson)

- OS: Raspberry Pi OS Bookworm (64-bit). It uses **NetworkManager**, so the same
  `nmcli` approach as the Jetson works. (On an older dhcpcd-based OS, stop and
  tell the user to upgrade, rather than mixing in hostapd/dnsmasq.)
- Wi-Fi interface is **`wlan0`** (the Jetson's is `wlP1p1s0`). Confirm it with
  `nmcli device status`.
- The Pi 5 has **one Wi-Fi radio**: while it runs as a hotspot it can't also be a
  Wi-Fi client. Use ethernet for internet during setup (installing Node or npm
  packages). Warn the user before bringing the hotspot up if their SSH session
  runs over Wi-Fi, because that session will drop.
- Wi-Fi stays rfkill-blocked until a **country code** is set. Check with
  `rfkill list`, and fix with `sudo raspi-config nonint do_wifi_country US` (use the
  user's country if it's not the US).
- `sudo` usually needs a password, and NetworkManager refuses hotspot changes from
  a non-root user ("Insufficient privileges"). When a step needs root, hand the
  user the exact command to run rather than trying workarounds.

## Setup steps

1. **Repo**: clone or copy `InTheEyesOf` to the Pi (e.g. `~/workspace/InTheEyesOf`).
   `web-viewer/vite.config.ts` and `web-viewer/scripts/setup-hotspot.sh` must be
   the current versions from the Jetson (see "Lessons from the Jetson").
2. **Node**: install it per-user with nvm (no sudo, works on arm64):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
   export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm install 22
   ```
   In a non-interactive shell, `node` may still not be on PATH after `nvm install`.
   If so, prepend it directly:
   `export PATH="$(ls -d ~/.nvm/versions/node/v22*/bin):$PATH"`.
3. **Dependencies**: `cd web-viewer && npm install` (needs internet, so do this
   before the hotspot takes over Wi-Fi).
4. **Hotspot**: the shared script takes env overrides. The user runs this
   (it needs root), with the values for *this* Pi:
   ```bash
   # Pi 1
   sudo SSID=duo-pi-1 ADDR=10.42.1.1 IFACE=wlan0 CON=duo-pi-hotspot PASSWORD=intheeyesof \
     ./scripts/setup-hotspot.sh
   # Pi 2
   sudo SSID=duo-pi-2 ADDR=10.42.2.1 IFACE=wlan0 CON=duo-pi-hotspot PASSWORD=intheeyesof \
     ./scripts/setup-hotspot.sh
   ```
   Then pin the channel, which the script doesn't set (Pi 1 → 1, Pi 2 → 11):
   ```bash
   sudo nmcli connection modify duo-pi-hotspot 802-11-wireless.channel 1   # 11 on Pi 2
   sudo nmcli connection up duo-pi-hotspot
   ```
   The profile autoconnects with priority 100, so it comes back after a reboot.
5. **Dev server**: `cd web-viewer && npm run dev`. Vite already listens on all
   interfaces over HTTPS (`host: true`, port 5173).
6. **Optional, start on boot**: if the user wants the viewer up without logging
   in, create a systemd *user* service that runs `npm run dev` in `web-viewer/`,
   using nvm's node path, then run `loginctl enable-linger $USER` (that command
   needs sudo). Ask first; don't do this by default.

## Lessons from the Jetson (don't relearn these)

- **iOS sends plain `http://` to the HTTPS port.** Even when the user is sure
  they typed `https://`, Safari and Chrome on iPad often connect over plain HTTP.
  The TLS server drops those connections, and the browser shows only
  "connection was lost" / "connection closed", with no certificate warning.
  `vite.config.ts` contains an `httpToHttpsRedirect` plugin that sniffs the first
  byte of each connection and answers non-TLS traffic with a 301 to https. Keep it.
- **That plugin attaches a `socket.on('error')` handler on purpose.** Without one,
  a client that resets the connection before TLS starts crashes the whole Vite
  process, and the hotspot looks broken when the dev server is simply dead. If the
  page stops loading, first check that something is listening:
  `ss -ltnp | grep 5173`.
- **The certificate is self-signed for localhost only** (`@vitejs/plugin-basic-ssl`),
  so every client gets a "not private" warning once. Tell users to tap
  Show Details → visit this website. TLS errors show in the Vite log as
  `[https] TLS error from <ip>`. `CERTIFICATE_UNKNOWN` (alert 46) just means the
  user hasn't accepted the warning yet.
- **The hotspot has no internet, and iOS may quietly switch to cellular.** If a
  device can't reach the page, check that it's still joined to `duo-pi-N`, and
  turn off cellular data, VPNs and "Limit IP Address Tracking" for that network.

## Verifying a Pi

Run these on the Pi (use `10.42.2.1` on Pi 2):

```bash
nmcli -t device status | grep wlan0          # → connected:duo-pi-hotspot
ip -4 addr show wlan0 | grep inet            # → 10.42.1.1/24
ss -ltnp | grep 5173                         # vite listening
curl -sk -o /dev/null -w '%{http_code}\n' https://10.42.1.1:5173/   # → 200
curl -s  -o /dev/null -w '%{http_code} %{redirect_url}\n' http://10.42.1.1:5173/
                                             # → 301 https://10.42.1.1:5173/
ip neigh show dev wlan0                      # connected clients
```

If a client is joined but the page won't load, figure out which layer fails
before changing anything:
1. A plain-HTTP test server on another port (e.g. a tiny Node `net` server on
   5174) tells you whether the client reaches the Pi at all.
2. `ss -tn | grep <client-ip>` shows whether connections reach port 5173, and
   `FIN-WAIT-2` on the Pi's side means the Pi closed them.
3. The Vite log, which shows TLS errors.

## Undo

```bash
sudo nmcli connection delete duo-pi-hotspot   # Wi-Fi returns to client mode
```
