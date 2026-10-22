#!/usr/bin/env bash
# Turn the Jetson's Wi-Fi into an access point so phones/laptops can connect
# directly and open the web viewer. Run with: sudo ./scripts/setup-hotspot.sh
# Override defaults with env vars: SSID=... PASSWORD=... IFACE=... ADDR=... CON=...
set -euo pipefail

SSID="${SSID:-InTheEyesOf-Jetson}"
PASSWORD="${PASSWORD:-intheeyesof}"   # WPA2 needs >= 8 chars
IFACE="${IFACE:-wlP1p1s0}"
ADDR="${ADDR:-10.42.0.1}"           # hotspot gateway IP (/24)
CON="${CON:-jetson-hotspot}"     # NetworkManager profile name

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

nmcli connection delete "$CON" >/dev/null 2>&1 || true

nmcli connection add type wifi ifname "$IFACE" con-name "$CON" \
  autoconnect yes connection.autoconnect-priority 100 \
  ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared ipv4.addresses "$ADDR/24" \
  ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASSWORD"

nmcli connection up "$CON"

echo
echo "Hotspot up:  SSID=$SSID  password=$PASSWORD"
echo "Web viewer:  https://$ADDR:5173  (after 'npm run dev')"
echo "GPS relay:   ws://$ADDR:8080"
echo "Undo:        sudo nmcli connection delete $CON"
