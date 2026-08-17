# Automatische nieuwsbrief via GitHub Actions

Deze workflow (`.github/workflows/nieuwsbrief.yml`) genereert elke ochtend automatisch
een nieuwe editie van de Israël-nieuwsbrief — volledig in de cloud, onafhankelijk van
of er ergens een pc aanstaat.

## Werking
1. `scripts/generate_newsletter.py` roept de Anthropic API aan met de web search tool,
   verzamelt het nieuws van de afgelopen dagen en levert JSON.
2. Het script vult `scripts/template.html` (met behoud van styling; géén voorleesknop)
   tot een volledige `index.html`, bewaart een kopie in `edities/` en werkt
   `edities/gebruikte-items.txt` bij (nieuwe URL's toevoegen, ouder dan 14 dagen wissen).
3. De workflow commit en pusht; GitHub Pages publiceert automatisch.

## Eenmalige instelling
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Naam: `ANTHROPIC_API_KEY`
   - Waarde: je Anthropic API-sleutel (console.anthropic.com)
2. (Optioneel) Repo-variable `ANTHROPIC_MODEL` als je een ander model wilt.
3. Controleer dat **Settings → Actions → General → Workflow permissions** op
   "Read and write permissions" staat (of laat de `permissions:` in de workflow dit regelen).

## Testen
Actions-tab → "Dagelijkse Israel-nieuwsbrief" → **Run workflow**.

## Tijdstip en betrouwbaarheid
De workflow probeert het **vier keer per dag**: 03:40, 04:40 en 05:40 UTC (dus tussen
05:40 en 07:40 Nederlandse tijd) en als laatste vangnet 10:10 UTC. Elke poging kijkt
eerst of `edities/israel-nieuwsbrief-<vandaag>.html` al bestaat en stopt dan meteen,
dus er komt nooit een dubbele editie. GitHub kan cron-jobs tot een uur vertragen;
daarom die marge vóór 8:00.

Binnen het script zitten **vier pogingen** met oplopende wachttijd bij tijdelijke
API-fouten (rate limit, overbelasting, netwerkfout). De push wordt drie keer
geprobeerd met `git pull --rebase` ertussen.

## Zichtbaar als het toch misgaat
De pagina bevat een datumstempel ("Bijgewerkt: ...") en een oranje waarschuwingsbalk
die verschijnt zodra de editie niet van vandaag is. Zo zie je op je telefoon direct
dat er iets hapert in plaats van ongemerkt oud nieuws te lezen.

## Handmatig draaien
Actions-tab -> "Dagelijkse Israel-nieuwsbrief" -> **Run workflow**. Vink `force` aan
om een bestaande editie van vandaag te overschrijven.
