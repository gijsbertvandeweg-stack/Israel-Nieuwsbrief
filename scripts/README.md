# Automatische nieuwsbrief via GitHub Actions

Deze workflow (`.github/workflows/nieuwsbrief.yml`) genereert elke ochtend automatisch
een nieuwe editie van de Israël-nieuwsbrief — volledig in de cloud, onafhankelijk van
of er ergens een pc aanstaat.

## Werking
1. `scripts/generate_newsletter.py` roept de Anthropic API aan met de web search tool,
   verzamelt het nieuws van de afgelopen dagen en levert JSON.
2. Het script vult `scripts/template.html` (met behoud van styling én de voorleesknop)
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

## Tijdstip
De cron staat op `8 6 * * *` (06:08 UTC). Dat is 08:08 in de Nederlandse zomertijd
en 07:08 in de wintertijd. Pas de cron aan als je een vast lokaal tijdstip wilt.
