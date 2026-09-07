# GitHub-toegang voor updates (privérepo)

De update-knop en de terminal-updater halen code uit deze repository. Op een
**publieke** repo hoef je niets in te stellen. Op een **privérepo** heeft het
toestel een token nodig — voor twee dingen:

1. de **update-check** (`/releases/latest` via de GitHub-API), en
2. de **clone** van de release (`git clone`).

Een read-only **fine-grained token** dekt beide in één keer en is daarom de
aanbevolen aanpak.

## Aanmaken (eenmalig)

1. GitHub → **Settings → Developer settings → Fine-grained tokens → Generate new**.
2. **Repository access**: *Only select repositories* → alleen `ViejoolBel`.
3. **Permissions → Repository permissions → Contents: Read-only**.
4. Kies een vervaldatum (of plan rotatie) en maak het token aan. Kopieer het.

## Op het toestel plaatsen

Zet het token in het env-bestand dat de service al inleest, en beveilig het:

```bash
echo 'VIEJOOLBEL_GITHUB_TOKEN=github_pat_XXXXXXXX' | sudo tee -a /etc/viejoolbel/viejoolbel.env
sudo chmod 600 /etc/viejoolbel/viejoolbel.env
sudo systemctl restart viejoolbel
```

Vanaf nu:

- **Update-check** stuurt het token mee als `Authorization: Bearer …`, zodat de
  knop "Zoek naar updates" ook op een privérepo werkt.
- **`apply_update.sh`** laadt hetzelfde env-bestand en kloont via
  `https://x-access-token:<token>@github.com/…`, dus zowel de knop als de
  terminalcommando's werken.

## Veiligheid

- Gebruik **read-only** en **alleen deze repo** — nooit een token met schrijf- of
  brede toegang.
- Het token staat alleen in `/etc/viejoolbel/viejoolbel.env` (`chmod 600`), nooit
  in git. Het wordt niet in logs of in de webinterface getoond.
- Wil je het token intrekken? Verwijder de regel uit het env-bestand (of trek het
  in op GitHub) en herstart de service.

## Alternatief: deploy key (alleen clone)

Een read-only **deploy key** (SSH) kan de *clone* afhandelen, maar **niet** de
API-check — op een privérepo blijft de knop dan 404 geven. Gebruik daarom een
token als je de knop wilt, of zet de repo tijdelijk op publiek.
