# Monitoring & alerting

The bell rings from a **local** schedule, so it keeps working with no internet at
all. What monitoring buys you is a *notification* when the device needs attention
— a failed ring, a wrong clock, low disk, or the device dropping off the network
entirely — so you find out before the school does.

There are two independent mechanisms, and you want **both**: they catch different
failures.

## 1. Webhook alert (device is still online)

When a health check transitions to a fault (scheduler down, clock unset, a failed
ring, low disk) the device POSTs a short JSON message to a URL you choose. This
needs the device to be online at that moment.

The easiest target is **[ntfy.sh](https://ntfy.sh)** — free, no account:

1. Pick a hard-to-guess topic, e.g. `viejool-bel-9f3k`.
2. Install the ntfy app on your phone and subscribe to that topic.
3. In **Instellingen → Meldingen bij problemen**, set the webhook URL to
   `https://ntfy.sh/viejool-bel-9f3k` and click **Opslaan**, then **Stuur
   testmelding** to confirm it reaches your phone.

Discord, Slack and Home Assistant webhooks work too — paste their incoming-webhook
URL instead.

## 2. Heartbeat / dead man's switch (device is offline or dead)

This is the only thing that can catch a device that is **fully offline, powered
down, or stuck in AP mode** — exactly the "the bell disappeared" case. While
healthy, the device periodically pings a URL; if the pings stop, that external
service alerts you.

Use **[healthchecks.io](https://healthchecks.io)** (free tier):

1. Create a check. Set its **period** to 15 minutes and a **grace** of ~10 minutes
   (the device pings every 15 min by default — `heartbeat_interval_seconds`).
2. Add your email (and/or push, Telegram, etc.) as the notification method.
3. Copy the check's ping URL (looks like `https://hc-ping.com/xxxxxxxx-....`).
4. In **Instellingen → Meldingen bij problemen**, paste it as the **Heartbeat-URL**
   and click **Opslaan**.

Now, if the device disappears, healthchecks.io emails you within ~25 minutes.

> Why both? When the offline safety net opens the recovery AP, the device goes
> offline — so the webhook alert may not get out (it is now sent *just before* the
> radio switches, best-effort). The heartbeat is what reliably notices the silence
> that follows.

## Post-mortem: what happened while you were away

Health transitions and every time the safety net opens the AP are written to a
**durable event log** in the database (survives reboots), shown under
**Instellingen → Meldingen → Recente systeemgebeurtenissen** and available at
`GET /api/events`.

For the underlying system logs (WiFi drops, reboots), use `journalctl` on the Pi:

```bash
# The safety net opening the AP, and the daily ring plan:
journalctl -u viejoolbel --since "today 08:00" | grep -i "safety net\|Planned"
# What happened to WiFi:
journalctl -u NetworkManager --since "today 08:00"
# Did a given bell actually ring? (ts is UTC; CEST = UTC+2)
sqlite3 /var/lib/viejoolbel/viejoolbel.db \
  "select ts, source, sound_name, ok, detail from ring_log order by ts desc limit 20;"
```

## Robustness: offline safety net

Instellingen → AP has two knobs:

- **Open de AP na … minuten zonder netwerk** (`ap_fallback_minutes`, default 15):
  how long the WiFi link may be down before the device opens the recovery AP
  `ViejoolBel-Setup`. `0` disables the safety net entirely.
- **Herstart daarna vanzelf na … minuten** (`ap_fallback_recovery_minutes`,
  default 10): after the AP opens, the device reboots after this many minutes and
  retries its WiFi on its own, so a transient outage needs no site visit. `0`
  keeps the AP up until you reboot manually.

The bell keeps ringing from its local schedule throughout — none of this affects
whether bells sound, only whether the device stays reachable on the network.
