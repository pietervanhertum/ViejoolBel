# Updates publiceren en installeren

Deze gids legt uit **hoe jij een nieuwe versie uitbrengt** en **hoe die op het
toestel terechtkomt**. Voor het schoolpersoneel volstaat één knop; het echte werk
(een release maken) doe jij.

## Hoe het mechanisme werkt

1. Jij maakt een **GitHub Release** met een versietag (bv. `v0.2.0`) in deze repo.
2. Het toestel vraagt via de knop **Instellingen → Zoek naar updates** de
   *laatste release* op (`/releases/latest`) en vergelijkt die met zijn eigen
   versie (`viejoolbel/__init__.py` → `__version__`).
3. Bij **Installeer** haalt het toestel die tag op in een **nieuwe** map, bouwt de
   omgeving, draait een **health-check**, en wisselt dan pas de `current`-symlink
   om en herstart. Mislukt de nieuwe versie, dan draait het **automatisch terug**
   naar de vorige versie — het toestel kan dus niet stukgaan door een update.

> Belangrijk: het toestel kijkt naar **Releases**, niet naar losse commits of
> branches. Een `git push` naar `main` alleen brengt dus nog niets naar de
> schoolbel; je moet een release (met tag) publiceren.

## Een update publiceren (jouw kant) — stap voor stap

### 1. Wijzigingen klaarzetten en testen
Werk op een branch, laat de tests groen zijn en merge naar `main`:

```bash
pytest -q && ruff check . && mypy viejoolbel   # alles groen
```

### 2. Versienummer verhogen
Verhoog het versienummer op **twee** plaatsen (ze moeten gelijk zijn — de
vergelijking gebruikt `__version__`):

- `viejoolbel/__init__.py` → `__version__ = "0.2.0"`
- `pyproject.toml` → `version = "0.2.0"`

Gebruik [semantische versies](https://semver.org/lang/nl/): `MAJOR.MINOR.PATCH`
(bv. een bugfix = `0.2.1`, een nieuwe functie = `0.3.0`). Voeg ook een regel toe
in `CHANGELOG.md`.

```bash
git add viejoolbel/__init__.py pyproject.toml CHANGELOG.md
git commit -m "Release v0.2.0"
git push origin main
```

### 3. Een GitHub Release maken
Dit maakt meteen de tag aan én publiceert de release die het toestel vindt.

**Via de website (eenvoudigst):**
1. Ga naar de repo → **Releases** → **Draft a new release**.
2. Bij *Choose a tag*: typ `v0.2.0` en kies **Create new tag on publish**.
3. Titel: `v0.2.0`, en schrijf kort wat er nieuw is (dit zien latere beheerders).
4. Klik **Publish release**.

**Of via de terminal** (met de GitHub CLI):

```bash
git tag v0.2.0
git push origin v0.2.0
gh release create v0.2.0 --title "v0.2.0" --notes "Wat er nieuw is…"
```

### 4. Installeren op het toestel
Open de webinterface van de schoolbel → **Instellingen → Zoek naar updates**.
Als `v0.2.0` verschijnt, klik **Installeer**. Het toestel herstart kort en draait
daarna de nieuwe versie. Ververs de pagina na ±1 minuut.

## Alternatief: updaten via de terminal (op het toestel)

Zonder de webknop kun je een versie ook rechtstreeks toepassen (met rollback):

```bash
sudo /opt/viejoolbel/current/deploy/apply_update.sh v0.2.0
```

## Terugdraaien

- Een **mislukte** update draait vanzelf terug — je hoeft niets te doen.
- Wil je bewust terug naar een oudere versie? Publiceer die niet opnieuw als
  “latest”, maar draai op het toestel:
  ```bash
  sudo /opt/viejoolbel/current/deploy/apply_update.sh v0.1.0
  ```
  De vorige release blijft ook bewaard onder `/opt/viejoolbel/releases/`.

## Veelgestelde vragen

**“Zoek naar updates” zegt dat het niet lukt.**
Het toestel heeft internet nodig om GitHub te bereiken, en er moet een
*gepubliceerde* release bestaan. Controleer beide.

**Ik heb wel getagd maar geen release gemaakt.**
`git tag` alleen is niet genoeg voor de knop: maak een **Release** (stap 3). De
terminalmethode werkt wel met een kale tag.

**Een pre-release verschijnt niet.**
`/releases/latest` negeert pre-releases en drafts. Publiceer een gewone release.

**Moet ik het versienummer echt bijwerken?**
Ja. Als `__version__` niet lager is dan de tag, ziet het toestel de release niet
als nieuwer en biedt het de update niet aan.
