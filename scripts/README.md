# Automatische nieuwsbrief via GitHub Actions

Deze workflow (`.github/workflows/nieuwsbrief.yml`) genereert elke ochtend automatisch
een nieuwe editie van de Israël-nieuwsbrief — volledig in de cloud, onafhankelijk van
of er ergens een pc aanstaat.

## Werking
1. **Fase 1 — vinden.** `scripts/generate_newsletter.py` roept de Anthropic API aan met
   de web search tool, verzamelt het nieuws van de afgelopen dagen en levert JSON.
2. **Fase 2 — lezen (optioneel, Firecrawl).** `scripts/firecrawl_verrijk.py` haalt elk
   gevonden bronartikel echt op. Daarmee kennen we de werkelijke publicatiedatum,
   vervangen we de URL door de canonieke variant (zonder tracking-parameters) en
   herkennen we overzichts- en liveblogpagina's. Items die aantoonbaar ouder zijn dan
   5 dagen vallen hier af.
3. **Fase 3 — herschrijven.** Een tweede, goedkopere modelcall (zonder web search)
   schrijft de samenvattingen opnieuw op basis van de échte artikeltekst in plaats van
   een zoeksnippet, en gooit dubbelingen samen.
4. Het script vult `scripts/template.html` (met behoud van styling; géén voorleesknop)
   tot een volledige `index.html`, bewaart een kopie in `edities/` en werkt
   `edities/gebruikte-items.txt` bij (nieuwe URL's toevoegen, ouder dan 14 dagen wissen).
5. De workflow commit en pusht; GitHub Pages publiceert automatisch.

Fase 2 en 3 zijn **volledig optioneel**. Ontbreekt `FIRECRAWL_API_KEY`, of valt Firecrawl
uit, dan slaat het script die fases over en verschijnt de brief zoals voorheen op basis
van alleen web search. De brief kan er dus nooit door uitvallen.

## Eenmalige instelling
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Naam: `ANTHROPIC_API_KEY`
   - Waarde: je Anthropic API-sleutel (console.anthropic.com)
2. (Aanbevolen) Tweede secret voor het uitlezen van bronartikelen:
   - Naam: `FIRECRAWL_API_KEY`
   - Waarde: je sleutel van firecrawl.dev
   - Voeg daarna in `.github/workflows/nieuwsbrief.yml` onder de stap
     "Nieuwsbrief genereren" bij `env:` deze regel toe:
     `FIRECRAWL_API_KEY: ${{ secrets.FIRECRAWL_API_KEY }}`
   Zonder die regel ziet het script de sleutel niet en draait het op alleen web search.
3. (Optioneel) Repo-variable `ANTHROPIC_MODEL` als je een ander model wilt.
4. Controleer dat **Settings → Actions → General → Workflow permissions** op
   "Read and write permissions" staat (of laat de `permissions:` in de workflow dit regelen).

## Testen
Actions-tab → "Dagelijkse Israel-nieuwsbrief" → **Run workflow**. In het logboek zie je
per run een regel `Fase 1 (web search): N kandidaat-items.` en, als Firecrawl actief is,
`Fase 2 (Firecrawl): gescraped=..., te_oud=..., indexpagina=...`. Daaraan zie je meteen
of de verrijking werkt en hoeveel items er om welke reden afvallen.

## Kosten
Firecrawl rekent per opgehaalde pagina (1 credit). Met 15-25 items per editie kom je op
ongeveer 450-750 credits per maand. Het scrapeverzoek gebruikt een cache van 6 uur, dus
een tweede run op dezelfde dag kost weinig extra.

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
