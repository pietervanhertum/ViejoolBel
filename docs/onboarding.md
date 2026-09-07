# Headless onboarding (no internet required)

Goal: bring a fresh device online at a school **without a screen, keyboard, or any
existing internet** (FR-19).

## How it works
At boot a small service (`viejoolbel-ap.service`) waits ~45 s for the Pi to join a
known WiFi network. If none is found it reconfigures `wlan0` as its own access
point and starts `hostapd` + `dnsmasq`:

- SSID **`ViejoolBel-Setup`** (password on the device label; default `belsetup2025`).
- The Pi is at **192.168.4.1**; the captive DNS points every hostname there, so any
  browser you open lands on the setup page.

Connect a phone/laptop to that network, open `http://192.168.4.1:8080`, and enter
the school's WiFi SSID + password. The device joins that network, tears the AP
down, and is then reachable at `viejoolbel.local`.

## Enabling the AP service
Copy the onboarding unit and enable it (the installer can be extended to do this):

```bash
sudo cp deploy/ap-onboarding/viejoolbel-ap.service /etc/systemd/system/
sudo systemctl enable viejoolbel-ap.service
```

Example unit (`deploy/ap-onboarding/viejoolbel-ap.service`):

```ini
[Unit]
Description=ViejoolBel onboarding access point
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/viejoolbel/current/deploy/ap-onboarding/viejoolbel-ap.sh 45
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

## Discovering the device on a LAN
Once on the school WiFi, the device advertises itself via mDNS/Avahi as
`viejoolbel.local`. If mDNS is blocked, find its IP from the router or via the
Tailscale admin console (see [`remote-support.md`](remote-support.md)).
