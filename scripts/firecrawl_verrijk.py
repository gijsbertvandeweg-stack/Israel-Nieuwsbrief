#!/usr/bin/env python3
"""Firecrawl-verrijking voor de Israel-nieuwsbrief.

Fase 1 (generate_newsletter.py) vindt kandidaat-items via web search.
Deze module leest de gevonden artikelen daadwerkelijk uit, zodat we:
  - de echte publicatiedatum kennen (i.p.v. gokken op een zoeksnippet);
  - index-/liveblog-URL's herkennen die dedupliceren onbruikbaar maken;
  - de volledige artikeltekst hebben voor een inhoudelijke samenvatting.

Alles faalt zacht: zonder API-sleutel of bij storing levert dit module de
items ongewijzigd terug, zodat de nieuwsbrief hoe dan ook verschijnt.
"""
import os, re, sys, json, time, datetime, urllib.request, urllib.error
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()
ENDPOINT = "https://api.firecrawl.dev/v2/scrape"

MAX_LEEFTIJD_DAGEN = 5
TIMEOUT = 60
WORKERS = 4
MAX_TEKST = 2500          # tekens artikeltekst die we doorgeven aan het model
CACHE_MS = 6 * 60 * 60 * 1000   # hergebruik Firecrawl-cache tot 6 uur oud

# Padnamen die duiden op een overzichts- of liveblogpagina in plaats van een artikel.
INDEX_PADEN = {
    "latest", "news", "israel-news", "israel-and-the-region", "world",
    "middle-east", "middleeast", "live", "livenews", "breaking-news",
    "israel-hamas-war", "category", "topics", "opinion",
}
DATUM_VELDEN = [
    "publishedTime", "article:published_time", "og:article:published_time",
    "datePublished", "published_time", "publishdate", "pubdate",
    "dc.date.issued", "date", "article:modified_time", "modifiedTime",
]


def beschikbaar():
    return bool(API_KEY)


def is_indexpagina(url):
    """True als de URL een overzichtspagina is en niet een los artikel."""
    try:
        pad = urlparse(url).path.strip("/").lower()
    except Exception:
        return False
    if not pad:
        return True                      # kale homepage
    if "liveblog" in pad or pad.startswith("live/"):
        return True
    if pad in INDEX_PADEN:
        return True
    # Eén padsegment kan zowel een rubriek ("israel-news") als een artikelslug
    # ("eisenkot-vows-no-compromise") zijn. Rubrieken zijn kort: hooguit twee
    # woorden en zonder cijfers. Alles daarboven behandelen we als artikel.
    delen = pad.split("/")
    if len(delen) == 1:
        woorden = [w for w in re.split(r"[-_]", delen[0]) if w]
        if len(woorden) <= 2 and not re.search(r"\d", delen[0]):
            return True
    return False


def _datum_uit_meta(meta):
    for veld in DATUM_VELDEN:
        waarde = meta.get(veld)
        if isinstance(waarde, list):
            waarde = waarde[0] if waarde else None
        if not isinstance(waarde, str):
            continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", waarde)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def _scrape(url):
    payload = json.dumps({
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "removeBase64Images": True,
        "maxAge": CACHE_MS,
    }).encode()
    laatste = None
    for poging in (1, 2):
        try:
            req = urllib.request.Request(ENDPOINT, data=payload, headers={
                "Authorization": f"Bearer {API_KEY}",
                "content-type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                antwoord = json.load(r)
            return antwoord.get("data") or {}
        except Exception as e:            # noqa: BLE001 - nooit de run laten klappen
            laatste = e
            if poging == 1:
                time.sleep(3)
    print(f"    Firecrawl mislukt voor {url}: {laatste}", file=sys.stderr)
    return {}


def verrijk(data, vandaag):
    """Vult per artikel _tekst, _datum, _status en corrigeert de bron-URL.

    Retourneert (data, statistiek-dict). Items ouder dan MAX_LEEFTIJD_DAGEN
    worden verwijderd; items zonder leesbare datum blijven staan maar worden
    gemarkeerd, zodat het model in fase 3 zelf kan besluiten.
    """
    stats = {"gescraped": 0, "te_oud": 0, "indexpagina": 0,
             "mislukt": 0, "datum_onbekend": 0, "verrijkt": 0}
    artikelen = [a for sec in data.get("secties", [])
                 for a in sec.get("artikelen", [])]
    if not artikelen:
        return data, stats

    grens = vandaag - datetime.timedelta(days=MAX_LEEFTIJD_DAGEN)

    def behandel(a):
        bronnen = a.get("bronnen") or []
        if not bronnen:
            a["_status"] = "geen bron"
            return
        url = bronnen[0].get("url", "")
        if is_indexpagina(url):
            a["_status"] = "indexpagina"
            stats["indexpagina"] += 1
        doc = _scrape(url)
        if not doc:
            a["_status"] = a.get("_status") or "scrape mislukt"
            stats["mislukt"] += 1
            return
        stats["gescraped"] += 1
        meta = doc.get("metadata") or {}

        # Canonieke URL overnemen: stabieler voor dedupliceren.
        canoniek = meta.get("url") or meta.get("sourceURL") or meta.get("og:url")
        if isinstance(canoniek, str) and canoniek.startswith("http") and not is_indexpagina(canoniek):
            bronnen[0]["url"] = canoniek.split("?")[0]

        datum = _datum_uit_meta(meta)
        a["_datum"] = datum.isoformat() if datum else None
        if datum is None:
            stats["datum_onbekend"] += 1
            a["_status"] = a.get("_status") or "datum onbekend"

        tekst = (doc.get("markdown") or "").strip()
        if tekst:
            a["_tekst"] = tekst[:MAX_TEKST]
            stats["verrijkt"] += 1
            a.setdefault("_status", "ok")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(behandel, artikelen))

    # Te oude items eruit (alleen als we de datum zeker weten).
    for sec in data.get("secties", []):
        houden = []
        for a in sec.get("artikelen", []):
            d = a.get("_datum")
            if d and d < grens.isoformat():
                stats["te_oud"] += 1
                continue
            houden.append(a)
        sec["artikelen"] = houden

    return data, stats
