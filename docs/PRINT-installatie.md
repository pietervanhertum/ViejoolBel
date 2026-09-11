# ViejoolBel — Installatiegids (voor de installateur)

*Afdrukbaar A4-document. Bewaar dit bij het toestel.*

Deze gids is voor wie het systeem installeert (technisch). De losse
**Gebruikershandleiding** (`PRINT-handleiding.md`) is voor het schoolpersoneel.

---

## 1. Wat je nodig hebt

- Raspberry Pi (3, 4 of Zero 2 W) met voeding (5 V, degelijke adapter).
- microSD-kaart (16 GB of meer).
- **DS3231 RTC-klokmodule** (sterk aanbevolen — de Pi heeft geen eigen klok en
  zou na een stroomonderbreking zonder internet de verkeerde tijd hebben).
- Eén of beide van:
  - **Speaker + versterker** (voor belgeluiden), of
  - **Relaismodule** die de bestaande elektrische schoolbel schakelt.
- Optioneel: drukknop ("bel nu") en status-LED.
- Een computer of telefoon om de webinterface te openen.

> ⚠️ De 230 V-kant van een elektrische bel moet door een **erkend elektricien**
> worden aangesloten via een correct gedimensioneerd relais/contactor. De Pi
> levert enkel een laagspannings-stuursignaal.

## 2. SD-kaart voorbereiden

1. Installeer **Raspberry Pi Imager** op je computer.
2. Kies **Raspberry Pi OS Lite (64-bit)**.
3. Klik op het tandwiel (instellingen) en zet:
   - hostnaam: `viejoolbel`
   - SSH inschakelen
   - (optioneel) wifi + land — mag je overslaan, het toestel kan later ook
     zónder internet worden ingesteld (zie stap 6).
4. Schrijf de kaart en steek ze in de Pi. Sluit speaker/relais aan en start op.

> 💡 **Ga je het toestel opsturen naar een school waar je zelf niet komt?**
> Stel de schoolwifi dan **op voorhand** in (zie stap 6a). Dan verbindt het
> toestel zich vanzelf zodra het daar wordt aangezet — de persoon ter plaatse
> hoeft dan enkel de stekker in te steken.

## 3. Software installeren

Verbind met de Pi (via SSH: `ssh pi@viejoolbel.local`) en voer uit:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/pietervanhertum/ViejoolBel
cd ViejoolBel
sudo ./deploy/install.sh
```

Het installatiescript doet alles automatisch: systeempakketten, een aparte
gebruiker, de applicatie, en de **automatische opstart** (systemd). Na afloop
draait ViejoolBel en start het **vanzelf opnieuw op na een stroomonderbreking**.

## 4. Real-time klok (DS3231) activeren

1. Sluit de DS3231 aan op de I²C-pinnen (SDA/SCL, 3V3, GND).
2. Zet in `/boot/firmware/config.txt` de regel: `dtoverlay=i2c-rtc,ds3231`
3. Schakel I²C in via `sudo raspi-config` → Interface Options → I2C.
4. Herstart. De Pi zet nu bij elke start zijn klok gelijk vanaf de RTC.

## 5. Eerste keer inloggen

- Open op je telefoon/computer: **`http://viejoolbel.local:8080`**
- Log in met gebruikersnaam **`admin`** en wachtwoord **`dirkteur`**.
- **Wijzig het wachtwoord** als je het wil aanpassen (Instellingen →
  "Wachtwoord wijzigen"). Zolang het nog op de standaardwaarde staat, blijft het
  dashboard hiervoor waarschuwen.

> 🔒 Dit wachtwoord (`admin` / `dirkteur`) staat **enkel** in deze
> installatiegids, niet in de gebruikershandleiding voor het schoolpersoneel.
> Geef het door aan wie het toestel mag beheren.

## 6. Installeren zonder dat er al wifi is

Er zijn twee manieren. Kies **6a** als je de schoolwifi al kent — dan hoeft er
ter plaatse niemand iets in te stellen. **6b** is de terugval als de wifi niet
op voorhand gekend is.

### 6a. Wifi op voorhand instellen (aanbevolen — "gewoon inpluggen")

Doe dit **thuis/op kantoor terwijl je het toestel klaarmaakt**, niet op school.
Het netwerk hoeft niet in de buurt te zijn: het toestel onthoudt de gegevens en
verbindt zodra dat netwerk in bereik komt. Voer op de Pi uit:

```bash
# De wifi van de school (hoger getal = voorkeur als er meerdere in bereik zijn):
sudo /opt/viejoolbel/current/deploy/preseed_wifi.sh "SchoolWifi" "schoolwachtwoord" 10

# Optioneel: je eigen werkbank-wifi, zodat je thuis nog kunt testen:
sudo /opt/viejoolbel/current/deploy/preseed_wifi.sh "WerkbankAP" "testwachtwoord" 1
```

Je kunt dit meerdere keren uitvoeren voor meerdere netwerken; het toestel kiest
zelf welk netwerk in bereik is. Stuur het toestel op → de school steekt enkel de
stekker in → het verbindt vanzelf en is bereikbaar op `viejoolbel.local`. De
instelpagina hieronder verschijnt dan niet.

> Alternatief kun je in **Raspberry Pi Imager** (stap 2) één wifi-netwerk
> vooraf invullen. Dat werkt ook, maar met het script kun je meerdere netwerken
> bewaren en de voorkeur bepalen — en het werkt ook op een reeds voorbereide kaart.

### 6b. Instellen ter plaatse via het toestel zelf (terugval)

Als er geen wifi vooraf is ingesteld, maakt het toestel zélf een wifi-netwerk aan
(dit staat standaard aan na de installatie):

1. Zoek op je telefoon het wifi-netwerk **`ViejoolBel-Setup`** (wachtwoord staat
   op het toestel-label, standaard `belsetup2025`).
2. Open een browser → je komt automatisch op de instelpagina (of ga naar
   `http://192.168.4.1:8080`).
3. Vul de wifi van de school in. Het toestel verbindt en is daarna bereikbaar
   op `viejoolbel.local`.

*(Zie `docs/onboarding.md` voor de details.)*

## 7. Support op afstand (zonder aan het schoolnetwerk te raken)

Installeer **Tailscale** zodat je het toestel van thuis kunt bereiken zonder
poorten open te zetten of iets aan de router van de school te wijzigen:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname viejoolbel
```

Daarna bereik je de webinterface via `http://viejoolbel:8080` op je eigen
Tailscale-netwerk. *(Zie `docs/remote-support.md`.)*

## 8. Meldingen bij problemen instellen

In de webinterface, onderaan bij **"Meldingen bij problemen"**:

- **Webhook-URL**: krijgt een bericht zodra er iets misgaat (bv. een gratis
  `https://ntfy.sh/kies-een-unieke-naam` — installeer de ntfy-app op je telefoon
  en abonneer op diezelfde naam).
- **Heartbeat-URL**: waarschuwt jou als het toestel **helemaal offline of uit**
  gaat (bv. een gratis check op `https://healthchecks.io`). Dit is de enige manier
  om een uitgevallen of stroomloos toestel te detecteren.
- **"Stuur een info-melding bij het opstarten"** (standaard aan): het toestel
  stuurt bij elke start een info-bericht met versie, tijd, tijd-sinds-boot en het
  verbonden wifi-netwerk. Zo zie je het terugkomen na een stroompanne of een
  zelf-herstel-herstart.

Klik op **"Stuur testmelding"** om te controleren of het werkt.

> 💡 Zet **beide** in: de webhook vangt fouten terwijl het toestel online is; de
> heartbeat vangt een toestel dat volledig wegvalt. Zie `docs/monitoring.md` voor
> de volledige opzet.

### Achteraf uitzoeken wat er gebeurde (post-mortem)

Onder **"Recente systeemgebeurtenissen"** (in dezelfde sectie) staat een
duurzaam logboek dat een **herstart overleeft**: je ziet er wanneer een controle
faalde, wanneer het vangnet het setup-netwerk opende, en elke keer dat het toestel
opstartte. Handig om achteraf te reconstrueren wat er misging zonder in
`journalctl` te hoeven duiken.

## 8b. Zelf-herstel bij netwerkuitval (Instellingen → AP)

Het toestel belt volledig **lokaal** — een netwerkstoring stopt de bel dus niet.
Om het toestel toch **bereikbaar** te houden en zichzelf te laten herstellen, staan
er twee instellingen onder **Instellingen → AP**:

- **"Open de AP na … minuten zonder netwerk"** (standaard 15, 0 = uit): valt de
  wifi-verbinding langer weg, dan opent het toestel het setup-netwerk
  `ViejoolBel-Setup` zodat je het ter plaatse kunt herstellen.
- **"Herstart daarna vanzelf na … minuten"** (standaard 10, 0 = uit): na het
  openen van de AP **herstart** het toestel automatisch en probeert het opnieuw op
  de schoolwifi te komen — een tijdelijke storing vereist zo geen plaatsbezoek.

> De bel blijft ondertussen gewoon rinkelen; dit bepaalt enkel de
> netwerk­bereikbaarheid. Zet de herstart-tijd op 0 als je niet wil dat het toestel
> uit zichzelf herstart.

## 9. Bijwerken (update)

Gebruik de updateknop in de webinterface, of via de terminal:

```bash
sudo /opt/viejoolbel/current/deploy/apply_update.sh v0.2.0
```

Updates zijn veilig: bij een probleem draait het toestel **automatisch terug**
naar de vorige werkende versie. Lijkt er niets te gebeuren na een update? Klik in
de webinterface op **"Toon updatelog"** (bij Instellingen) om te zien wat er
gebeurd is — daar staat de laatste stap en een eventuele fout.

> 💡 De **versie** die het toestel écht draait, staat onderaan in de
> webinterface. Ververst je na een update de pagina en zie je nog de oude
> UI? Doe een **harde herlaad** (Ctrl+F5, of op de telefoon: pagina volledig
> sluiten en opnieuw openen).

## 10. Handige commando's

```bash
journalctl -u viejoolbel -f          # live logboek bekijken
sudo systemctl restart viejoolbel    # herstarten
sudo systemctl status viejoolbel     # status + laatste gezondheid
```

## 11. Instellen in de webinterface (na de installatie)

Deze stappen doe je in de browser, ná stap 5. Ze bepalen hoe de bel bij deze
school precies moet werken.

### Uitvoer: audio en/of relais

Ga naar **Instellingen → Uitvoer**. Hier zet je aan wat dit toestel gebruikt:

- **Speaker/audio** aan als de school via een luidspreker belt.
- **Relais** aan als het toestel de bestaande elektrische schoolbel schakelt.

Belt de school **enkel via de speaker**? Zet het **relais uit**. Dan verdwijnt
het relais overal uit beeld (bij "Bel nu", in het rooster en bij het plan van
vandaag) en wordt het nooit geschakeld — dat maakt het scherm eenvoudiger voor
het personeel.

### Standaardbel kiezen

Ga naar **Geluiden** en klik bij één geluid op **"Maak standaard"**. Die
standaardbel wordt gebruikt door de **fysieke knop** op het toestel en staat
voorgeselecteerd bij "Bel nu". Zo hoeft het personeel niets te kiezen.

### Rooster, kalender en volume

- Vul onder **Roosters** het weekrooster en de beltijden in.
- Vul onder **Kalender** de vakanties en vrije dagen in.
- Stel onder **Instellingen** het **volume** in (voor de speaker).

### Back-up en herstellen

Onder **Instellingen** kun je met **"Back-up"** de volledige configuratie
(roosters, kalender, geluidsnamen en instellingen) als één bestand downloaden.
Bewaar dat bestand goed. Met **"Herstellen"** zet je die configuratie terug op
dit of een vervangend toestel — geluiden worden op naam teruggekoppeld.

---

### Checklist eerste gebruik (in de webinterface)
Doe dit onmiddellijk na het inloggen, vóór je het toestel oplevert:
- [ ] Ingelogd op `viejoolbel.local:8080` met `admin` / `dirkteur`
- [ ] Wachtwoord gewijzigd (of bewust op standaard gelaten en doorgegeven)
- [ ] **Uitvoer** ingesteld (speaker en/of relais; relais uit als enkel audio)
- [ ] **Standaardbel** aangeduid bij Geluiden
- [ ] Weekrooster (Roosters) ingevuld
- [ ] Vakanties/vrije dagen (Kalender) ingevuld
- [ ] Volume ingesteld en getest via **Zelftest**
- [ ] **Back-up** gedownload en veilig bewaard

---

### Checklist na installatie (technisch)
- [ ] Wifi verbindt automatisch (vooraf ingesteld met `preseed_wifi.sh`, of via
      `ViejoolBel-Setup`) en toestel is bereikbaar op `viejoolbel.local`
- [ ] Installatiescript zonder fouten doorlopen; dienst draait
      (`sudo systemctl status viejoolbel`)
- [ ] DS3231 RTC werkt (tijd klopt na herstart zonder internet)
- [ ] Toestel start vanzelf op na een stroomonderbreking (test: stekker uit/in)
- [ ] Meldingen (webhook + heartbeat) ingesteld en getest
- [ ] Opstart-melding ontvangen (verschijnt bij het herstarten van de dienst)
- [ ] Zelf-herstel gecontroleerd (Instellingen → AP: vangnet + herstart-tijd)
- [ ] Tailscale actief voor support op afstand
