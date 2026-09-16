# Public access for staff — a login-protected public URL

Some school staff need to reach ViejoolBel **without installing Tailscale** — from
a phone, from home, from any browser. This guide exposes the web UI at a public
address such as **`https://bel.ottorosie.com`**, with a real per-person login *in
front of* the app, while keeping the project's core rule intact: **no
port-forwarding and no changes to the school's network** (FR-21).

We use **Cloudflare Tunnel** (the connector `cloudflared`) plus **Cloudflare
Access** (Cloudflare's Zero Trust login). It is essentially "Tailscale Funnel done
right for this use case": a custom domain *and* an authentication gate, with
nothing for you to host or operate.

> **Tailscale vs. this.** Keep Tailscale for *your own* remote support (SSH +
> UI over the tailnet — see [`remote-support.md`](remote-support.md)). Use this
> Cloudflare setup for *staff who can't or won't install Tailscale*. They coexist
> happily.

## How it works

```
 staffer's browser
        │  https://bel.ottorosie.com
        ▼
 Cloudflare edge ── Access login (email code / Google / Microsoft) ──┐
        │  authenticated request + signed JWT                        │
        ▼                                                            │
 cloudflared on the Pi  (outbound-only tunnel, no inbound ports)     │
        │  http://localhost:8080  (+ Cf-Access-Jwt-Assertion)        │
        ▼                                                            │
 ViejoolBel  ── verifies the Access JWT, then its own password login ┘
```

* The Pi makes only **outbound** connections to Cloudflare — same NAT-friendly
  principle as Tailscale, so the school router is untouched and no ports open.
* **Cloudflare Access** authenticates the visitor *before* the request reaches
  the Pi, giving you **per-person identity, MFA, and instant revocation** —
  a real improvement over the app's single shared password.
* ViejoolBel then **verifies the Access JWT** itself (defence in depth), so the
  UI can't be reached through the public hostname without having passed Access,
  even if a policy is later misconfigured. The app password stays on as a second
  factor.

**Availability:** this is remote *access* only. The bell schedule runs locally,
so a Cloudflare or internet outage means "no remote UI", never "no bell". On-site
the UI is still at `viejoolbel.local:8080` on the LAN.

## Prerequisites

1. The domain **`ottorosie.com` is on Cloudflare** (its nameservers point to
   Cloudflare). The **Free** plan is fine.
2. **Cloudflare Zero Trust** is enabled for your account (Access is free for up
   to 50 users — ample for a school).

## Step 1 — Install `cloudflared` on the Pi

A helper script installs it from Cloudflare's official apt repository (so it gets
security updates) and is arch-aware for the Pi:

```bash
sudo ./deploy/cloudflared/install-cloudflared.sh
```

That is all `install-cloudflared.sh` does on its own — it installs the package and
prints the next steps. You then pick **one** of the two paths below.

## Step 2 — Create the tunnel

### Path A — Remotely-managed (recommended, least on-device config)

Routing and Access all live in the dashboard; the Pi just runs a token.

1. Cloudflare **Zero Trust → Networks → Tunnels → Create a tunnel** (type
   *Cloudflared*). Name it `viejoolbel`. Copy the **tunnel token** it shows.
2. Install + start the connector as a service with that token:
   ```bash
   sudo ./deploy/cloudflared/install-cloudflared.sh --token <TUNNEL_TOKEN>
   ```
3. In the tunnel's **Public Hostname** tab, add:
   * **Subdomain** `bel`, **Domain** `ottorosie.com`
   * **Service** `HTTP` → `localhost:8080`

### Path B — Locally-managed (gitops; config lives on the Pi)

```bash
cloudflared tunnel login                        # opens a browser once to authorise
cloudflared tunnel create viejoolbel            # prints the <TUNNEL_ID>
cloudflared tunnel route dns viejoolbel bel.ottorosie.com

sudo install -d /etc/cloudflared
sudo cp deploy/cloudflared/config.example.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml           # fill in the two <TUNNEL_ID> spots

sudo cp deploy/cloudflared/viejoolbel-tunnel.service \
    /etc/systemd/system/viejoolbel-tunnel.service
sudo systemctl daemon-reload
sudo systemctl enable --now viejoolbel-tunnel.service
```

> The tunnel **must** target `http://localhost:8080`. ViejoolBel's Access gate
> treats loopback requests as "arrived through the tunnel"; pointing it at a LAN
> IP instead would skip that check.

## Step 3 — Protect it with Cloudflare Access

In **Zero Trust → Access → Applications → Add an application** (Self-hosted):

1. **Application domain:** `bel.ottorosie.com`.
2. **Session duration:** e.g. 24 hours.
3. Add a **policy**, Action **Allow**, with a rule that matches your staff —
   either **Emails** (list each staffer) or **Emails ending in** `@ottorosie.com`
   if they have addresses on that domain. Pick a login method (a one-time PIN
   emailed to them needs no accounts at all; Google/Microsoft SSO also work).
4. Save. Note the application's **Application Audience (AUD) tag** (Overview tab) —
   you need it next.

Visit `https://bel.ottorosie.com`: you should hit the Cloudflare login, then the
ViejoolBel password page.

## Step 4 — Turn on the app-side Access gate (defence in depth)

This makes ViejoolBel reject any tunnel request that didn't come through Access.

1. Install the extra (adds PyJWT) into the app's venv and set the two values in
   `/etc/viejoolbel/viejoolbel.env`:

   ```bash
   sudo /opt/viejoolbel/current/.venv/bin/pip install --no-cache-dir \
       '/opt/viejoolbel/current[access]'

   sudo tee -a /etc/viejoolbel/viejoolbel.env >/dev/null <<'EOF'
   VIEJOOLBEL_CF_ACCESS_TEAM_DOMAIN=ottorosie.cloudflareaccess.com
   VIEJOOLBEL_CF_ACCESS_AUD=<the AUD tag from step 3>
   EOF

   sudo systemctl restart viejoolbel
   ```

   Your **team domain** is shown in Zero Trust under **Settings → Custom Pages**
   (or your team name + `.cloudflareaccess.com`).

2. Check the logs say the gate is enabled:
   ```bash
   journalctl -u viejoolbel -e | grep -i "cloudflare access"
   ```

**Behaviour once enabled**

| Request path | What happens |
|---|---|
| `bel.ottorosie.com` via the tunnel, valid Access login | JWT verified → app password login |
| `bel.ottorosie.com` via the tunnel, no/invalid Access JWT | **403** before reaching the app |
| `viejoolbel.local:8080` on the school LAN | **Unaffected** — normal password login |
| Access configured but `[access]` extra not installed | Tunnel requests **denied** (fail closed); LAN + bell keep working |

If you skip step 4 the setup still works — Cloudflare Access still gates the
public URL — you just don't have the in-app double-check.

## Security notes

* Keep the app password strong. Access is the front door, but the UI is now
  reachable from the internet, so `changeme` must never be the live password.
* Access gives you a **per-person audit log** and lets you **remove one staffer**
  without changing a shared secret.
* No public origin IP exists — the Pi is reachable only *through* Cloudflare, so
  it can't be port-scanned or hit directly.
* To revoke everything fast, disable the Access application or stop the tunnel
  (`sudo systemctl stop cloudflared` or `viejoolbel-tunnel`); the bell keeps
  ringing regardless.

## Files in this repo

| File | Purpose |
|---|---|
| [`deploy/cloudflared/install-cloudflared.sh`](../deploy/cloudflared/install-cloudflared.sh) | Installs `cloudflared` (and, with `--token`, the service) |
| [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml) | Locally-managed tunnel config (Path B) |
| [`deploy/cloudflared/viejoolbel-tunnel.service`](../deploy/cloudflared/viejoolbel-tunnel.service) | systemd unit for the locally-managed tunnel |
