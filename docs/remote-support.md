# Remote support without touching the school's network

You want to support the device from home **without** port-forwarding, a static IP,
or any change to the school's router/firewall (FR-21). ViejoolBel uses
[Tailscale](https://tailscale.com), a mesh VPN built on WireGuard.

## Why this works
The device makes only **outbound** connections to Tailscale's coordination server
and then peers directly with your machines (NAT traversal; falls back to encrypted
relays if a firewall is strict). Because nothing inbound is needed, the school's
network is untouched and no ports are opened. Traffic is end-to-end encrypted.

## Setup
On the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname viejoolbel
```

`--ssh` lets you SSH in over the tailnet (handy for support); the web UI is then
reachable at `http://viejoolbel:8080` from any device on your tailnet.

### Unattended / pre-authorised
For fleet installs, generate an **auth key** in the Tailscale admin console and
pass it so the device joins without an interactive login:

```bash
sudo tailscale up --ssh --hostname viejoolbel --authkey tskey-xxxxxxxx
```

Consider tagging devices (e.g. `--advertise-tags=tag:bell`) and using ACLs so a
support account can reach only the bell devices.

## Alternatives considered
- **ZeroTier** — equivalent mesh VPN; swap the install step if you prefer it.
- **Reverse SSH tunnel to your own VPS** — no third-party service, but you operate
  the VPS and it is more brittle. See `DESIGN.md §4.3`.

## Security notes
- Keep the web UI password strong even behind the VPN (defence in depth).
- Remote SSH is gated by Tailscale identity + ACLs, not a public key on the
  internet.
