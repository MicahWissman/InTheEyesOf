# hotspot-forward.ps1 — Let phones on the laptop's Windows Mobile Hotspot reach the viewer
# running inside WSL2 (NAT mode), by forwarding a Windows port to the WSL VM.
#
# Run in an *Administrator* PowerShell (WSL path works directly):
#   powershell -ExecutionPolicy Bypass -File \\wsl.localhost\EyesOf\home\micah\workspace\ITEO\InTheEyesOf\web-viewer\scripts\hotspot-forward.ps1
#   ... -Port 5173          # forward the dev server instead of `vite preview`
#   ... -Remove             # undo the forward and firewall rule
#
# The WSL IP changes after a reboot / `wsl --shutdown` — just run this again.

param(
  [int]$Port = 4173,
  [string]$Distro = 'EyesOf',   # the distro serving the viewer (not necessarily the WSL default)
  [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$ruleName = "ITEO viewer $Port"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Error 'Run this from an Administrator PowerShell.' }

if ($Remove) {
  netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port | Out-Null
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  Write-Host "Removed forward and firewall rule for port $Port."
  exit 0
}

$wslIp = ((wsl.exe -d $Distro hostname -I) -split '\s+' | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1)
if (-not $wslIp) { Write-Error 'Could not read the WSL IP (is WSL running?).' }

# Replace any stale forward from a previous WSL IP
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port connectaddress=$wslIp connectport=$Port | Out-Null

# Hotspot clients land on a Public-profile network, so the rule must cover all profiles
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null
}

$hotspotIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.137.*' } | Select-Object -First 1).IPAddress
Write-Host "Forwarding Windows :$Port -> WSL ${wslIp}:$Port"
if ($hotspotIp) {
  Write-Host "Phones on the hotspot: https://${hotspotIp}:$Port/?recording=robotics_lab_combined"
} else {
  Write-Host 'Mobile hotspot not detected (no 192.168.137.x address) - turn it on in Settings > Network & internet > Mobile hotspot.'
}
