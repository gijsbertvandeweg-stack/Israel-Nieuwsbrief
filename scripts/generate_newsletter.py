#!/usr/bin/env python3
"""Genereert de dagelijkse Israël-nieuwsbrief via de Anthropic API (met web search)
en werkt index.html, edities/ en gebruikte-items.txt bij. Bedoeld voor GitHub Actions."""
import os, re, sys, json, time, html as htmllib, datetime, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import firecrawl_verrijk

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not API_KEY:
    sys.exit("FOUT: de omgevingsvariabele ANTHROPIC_API_KEY is leeg of ontbreekt. "
             "Zet hem als repository-secret via Settings -> Secrets and variables -> Actions.")

# Herkansingen bij tijdelijke storingen (rate limit, overbelasting, netwerk).
POGINGEN = 4
WACHT = [20, 60, 150]  # seconden tussen de pogingen
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAANDEN = ["januari","februari","maart","april","mei","juni","juli","augustus",
           "september","oktober","november","december"]
DAGEN = ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"]

def nl_datum(d):
    lang = f"{DAGEN[d.weekday()]} {d.day} {MAANDEN[d.month-1]} {d.year}"
    return lang, lang[0].upper()+lang[1:]

def lees_editienummer():
    try:
        idx = open(os.path.join(ROOT,"index.html"),encoding="utf-8").read()
        m = re.search(r"Editie\s+(\d+)", idx)
        if m: return int(m.group(1))+1
    except FileNotFoundError:
        pass
    return 1

def lees_gebruikte():
    p = os.path.join(ROOT,"edities","gebruikte-items.txt")
    if os.path.exists(p):
        return open(p,encoding="utf-8").read()
    return ""

def anthropic_call(messages, system, met_zoeken=True):
    """Voert een Messages-request uit en handelt pause_turn af tot het model
    klaar is. Met met_zoeken=False draait de call zonder web search; dat is
    goedkoper en gebruiken we voor het herschrijven op basis van scrapes."""
    url = "https://api.anthropic.com/v1/messages"
    tools = [{"type":"web_search_20250305","name":"web_search","max_uses":8}] if met_zoeken else []
    while True:
        body = {"model":MODEL,"max_tokens":16000,"system":system,
                "messages":messages,"tools":tools}
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
            headers={"x-api-key":API_KEY,"anthropic-version":"2023-06-01",
                     "content-type":"application/json"})
        resp = None
        for poging in range(1, POGINGEN + 1):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    resp = json.load(r)
                break
            except urllib.error.HTTPError as e:
                body_txt = e.read().decode(errors="replace")
                tijdelijk = e.code in (408, 409, 425, 429, 500, 502, 503, 504, 529)
                print(f"Poging {poging}/{POGINGEN}: Anthropic API gaf HTTP {e.code}: {body_txt[:800]}",
                      file=sys.stderr)
                if not tijdelijk or poging == POGINGEN:
                    print("FOUT: de API-aanroep is definitief mislukt.", file=sys.stderr)
                    raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                print(f"Poging {poging}/{POGINGEN}: netwerk- of leesfout: {e}", file=sys.stderr)
                if poging == POGINGEN:
                    print("FOUT: de API-aanroep is definitief mislukt.", file=sys.stderr)
                    raise
            time.sleep(WACHT[min(poging - 1, len(WACHT) - 1)])
        if resp is None:
            raise RuntimeError("Geen respons van de Anthropic API na alle pogingen.")
        if resp.get("stop_reason") == "pause_turn":
            # Vervolg de beurt: hang de assistant-content aan en herhaal.
            messages.append({"role":"assistant","content":resp["content"]})
            messages.append({"role":"user","content":"Ga verder."})
            continue
        if resp.get("stop_reason") == "max_tokens":
            print("WAARSCHUWING: max_tokens bereikt, response is mogelijk afgekapt", file=sys.stderr)
        text = "".join(b.get("text","") for b in resp.get("content",[]) if b.get("type")=="text")
        if not text.strip():
            print(f"FOUT: lege tekstrespons van de API. stop_reason={resp.get('stop_reason')!r}", file=sys.stderr)
            print(f"Volledige response: {json.dumps(resp)[:3000]}", file=sys.stderr)
        return text

def parse_json_antwoord(text, wat):
    """Haalt het JSON-blok uit een modelantwoord. None bij mislukking."""
    m = re.search(r"<<<JSON(.*?)JSON>>>", text, re.S)
    raw = m.group(1).strip() if m else text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    if not raw:
        print(f"FOUT: geen JSON gevonden in de respons ({wat}).", file=sys.stderr)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"FOUT: kon JSON niet parsen ({wat}): {e}", file=sys.stderr)
        print(f"Ontvangen tekst (eerste 3000 tekens): {raw[:3000]}", file=sys.stderr)
        return None


def strip_intern(data):
    """Verwijdert de _velden die alleen voor de verrijking dienden."""
    for sec in data.get("secties", []):
        for a in sec.get("artikelen", []):
            for sleutel in [k for k in a if k.startswith("_")]:
                a.pop(sleutel, None)
    return data


def herschrijf_met_bronteksten(data, lang):
    """Tweede modelcall: samenvattingen baseren op de echte artikeltekst."""
    voer = []
    for sec in data.get("secties", []):
        for a in sec.get("artikelen", []):
            if a.get("_tekst"):
                voer.append({"kop": a["kop"], "status": a.get("_status", "ok"),
                             "datum": a.get("_datum"), "brontekst": a["_tekst"]})
    if not voer:
        print("Verrijking: geen bronteksten opgehaald, samenvattingen blijven ongewijzigd.")
        return data

    schoon = strip_intern(json.loads(json.dumps(data)))
    prompt = f"""Hieronder staat de conceptnieuwsbrief voor {lang} en daarnaast de
werkelijke artikelteksten die zijn opgehaald bij de bronnen.

Herschrijf per artikel het veld "tekst" zodat het klopt met de brontekst: 2-4 zinnen
Nederlands, feitelijk, met concrete cijfers, namen en data uit het bronartikel in
plaats van algemeenheden. Laat "kop" en "bronnen" ongemoeid, tenzij de kop de lading
aantoonbaar niet dekt.

Verwijder een artikel volledig als uit de brontekst blijkt dat het ouder is dan 5 dagen,
dat het feit al in een eerdere editie stond, of dat het inhoudelijk hetzelfde is als een
ander artikel in deze editie. Werk in dat laatste geval de bronnen samen tot één artikel.
Pas de intro aan als er artikelen wegvallen.

CONCEPT:
{json.dumps(schoon, ensure_ascii=False)}

BRONTEKSTEN:
{json.dumps(voer, ensure_ascii=False)}

Lever UITSLUITEND JSON terug tussen de markers <<<JSON en JSON>>>, in exact hetzelfde
schema als het concept."""
    try:
        antwoord = anthropic_call(
            [{"role": "user", "content": prompt}],
            "Je bent eindredacteur van een Nederlandstalige nieuwsbrief over Israel. "
            "Je baseert je uitsluitend op de aangeleverde bronteksten en levert geldige JSON.",
            met_zoeken=False)
    except Exception as e:                                   # noqa: BLE001
        print(f"WAARSCHUWING: herschrijven mislukt ({e}); concept blijft staan.", file=sys.stderr)
        return data
    nieuw = parse_json_antwoord(antwoord, "herschrijven")
    if not nieuw or not nieuw.get("secties"):
        print("WAARSCHUWING: herschrijven gaf geen bruikbare JSON; concept blijft staan.",
              file=sys.stderr)
        return data
    aantal = sum(len(s.get("artikelen", [])) for s in nieuw["secties"])
    if aantal == 0:
        print("WAARSCHUWING: herschrijven liet geen artikelen over; concept blijft staan.",
              file=sys.stderr)
        return data
    return nieuw


def esc(s):
    return htmllib.escape(s, quote=True)

def bouw_content(data):
    parts = [f'<div class="intro">\n  <h2>In het kort</h2>\n  <p>{esc(data["intro"])}</p>\n</div>\n']
    for sec in data["secties"]:
        if not sec.get("artikelen"): continue
        parts.append(f'<section>\n  <h2 class="blok">{esc(sec["titel"])}</h2>\n')
        for a in sec["artikelen"]:
            bron = ", ".join(f'<a href="{esc(b["url"])}">{esc(b["naam"])}</a>' for b in a["bronnen"])
            parts.append(f'  <article>\n    <h3>{esc(a["kop"])}</h3>\n    <p>{esc(a["tekst"])}</p>\n    <p class="bron">Bron: {bron}</p>\n  </article>\n')
        parts.append('</section>\n')
    bronnen_namen = sorted({b["naam"] for sec in data["secties"] for a in sec.get("artikelen",[]) for b in a["bronnen"]})
    parts.append(f'<footer>\n  Samengesteld op basis van: {esc(", ".join(bronnen_namen))}. '
                 'Bij tegenstrijdige berichtgeving zijn beide lezingen vermeld. '
                 'Claims van strijdende partijen konden niet altijd onafhankelijk worden geverifieerd. '
                 'Volgende editie: morgen 8:00.\n</footer>')
    return "".join(parts)

def main():
    vandaag = datetime.date.today()
    lang, kap = nl_datum(vandaag)
    editie = lees_editienummer()
    gebruikte = lees_gebruikte()
    system = (
        "Je bent redacteur van een dagelijkse Nederlandstalige nieuwsbrief over Israël. "
        "Je zoekt op het web naar het meest recente nieuws en levert uitsluitend geldige JSON.")
    prompt = f"""Stel de nieuwsbrief samen voor {lang}.

Zoek met de web search tool naar het belangrijkste Israël-nieuws van de afgelopen 24 uur tot maximaal 5 dagen oud. Gebruik bronnen als Times of Israel, Haaretz, Jerusalem Post, JNS, i24news, CNN, BBC, israelnieuws.nl, israeltoday.nl, Israel Hayom, Axios, Al Jazeera (voor het Palestijnse perspectief bij Westoever-incidenten), Reuters en AP. Gebruik voor het blok Techniek & Economie bij voorkeur CTech/Calcalist en Globes. Gebruik voor het blok Religieus Nieuws bij voorkeur JTA, Aish.com en Chabad.org. Gebruik voor het blok Positief Nieuws bij voorkeur Israel21c en NoCamels.

SELECTIEREGELS (strikt):
- GEEN HERHALING: gebruik geen URL of nieuwsfeit dat al voorkomt in de lijst hieronder met eerder gebruikte items. Alleen een wezenlijk nieuwe ontwikkeling mag opnieuw; benoem dan wat nieuw is.
- MAX 5 DAGEN OUD, geef voorrang aan de laatste 24 uur. Twijfel je over de datum, laat het item weg.
- Dedupliceer: hetzelfde feit uit meerdere bronnen = één item met meerdere bronlinks.
- LINK NAAR HET ARTIKEL ZELF, nooit naar een overzichts- of liveblogpagina. Dus niet
  /latest/, niet /liveblog-.../ en niet de homepage, maar de directe artikel-URL. Kom je
  een feit alleen tegen in een liveblog, zoek dan het losse artikel erbij of laat het weg.

Verdeel het nieuws over deze blokken (laat een blok weg als er geen nieuws is):
🏛️ Politiek | ⚔️ Oorlog & Veiligheid | 💻 Techniek & Economie | ✡️ Religieus Nieuws | 🌟 Positief Nieuws

Blijf feitelijk en evenwichtig. Schrijf korte, krachtige headlines en per item 2-4 zinnen samenvatting in het Nederlands.

Lever UITSLUITEND JSON terug tussen de markers <<<JSON en JSON>>>, exact in dit schema:
<<<JSON
{{"intro":"3-5 zinnen met de belangrijkste ontwikkelingen",
"secties":[{{"titel":"🏛️ Politiek","artikelen":[{{"kop":"...","tekst":"...","bronnen":[{{"naam":"Times of Israel","url":"https://..."}}]}}]}}]}}
JSON>>>

Eerder gebruikte items (JJJJ-MM-DD URL), NIET opnieuw gebruiken:
{gebruikte}
"""
    text = anthropic_call([{"role":"user","content":prompt}], system)
    data = parse_json_antwoord(text, "concept")
    if not data:
        sys.exit(1)
    voor = sum(len(s.get("artikelen", [])) for s in data.get("secties", []))
    print(f"Fase 1 (web search): {voor} kandidaat-items.")

    # --- Fase 2: bronartikelen echt uitlezen via Firecrawl ---
    if firecrawl_verrijk.beschikbaar():
        try:
            data, stats = firecrawl_verrijk.verrijk(data, vandaag)
            print("Fase 2 (Firecrawl): " + ", ".join(f"{k}={v}" for k, v in stats.items()))
            na = sum(len(s.get("artikelen", [])) for s in data.get("secties", []))
            if na == 0:
                print("WAARSCHUWING: verrijking liet geen items over; run afgebroken.", file=sys.stderr)
                sys.exit(1)
            # --- Fase 3: samenvattingen herschrijven op basis van de brontekst ---
            data = herschrijf_met_bronteksten(data, lang)
        except SystemExit:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"WAARSCHUWING: verrijking overgeslagen door fout: {e}", file=sys.stderr)
    else:
        print("Fase 2 overgeslagen: FIRECRAWL_API_KEY ontbreekt, "
              "de brief draait op alleen web search.")

    data = strip_intern(data)
    if not any(s.get("artikelen") for s in data.get("secties", [])):
        print("FOUT: geen artikelen over om te publiceren.", file=sys.stderr)
        sys.exit(1)

    tmpl = open(os.path.join(ROOT,"scripts","template.html"),encoding="utf-8").read()
    page = (tmpl.replace("{{DATUM_LANG}}",esc(lang))
                .replace("{{DATUM_KAP}}",esc(kap))
                .replace("{{EDITIE}}",str(editie))
                .replace("{{DATUM_ISO}}",vandaag.isoformat())
                .replace("{{GEGENEREERD}}",datetime.datetime.now(datetime.timezone.utc)
                         .strftime("%d-%m-%Y %H:%M UTC"))
                .replace("{{CONTENT}}",bouw_content(data)))

    open(os.path.join(ROOT,"index.html"),"w",encoding="utf-8").write(page)
    os.makedirs(os.path.join(ROOT,"edities"),exist_ok=True)
    open(os.path.join(ROOT,"edities",f"israel-nieuwsbrief-{vandaag.isoformat()}.html"),"w",encoding="utf-8").write(page)

    # gebruikte-items.txt bijwerken (nieuwe URLs toevoegen, ouder dan 14 dagen wissen)
    p = os.path.join(ROOT,"edities","gebruikte-items.txt")
    regels = [l for l in gebruikte.splitlines() if l.strip()]
    for sec in data["secties"]:
        for a in sec.get("artikelen",[]):
            if a["bronnen"]:
                regels.append(f'{vandaag.isoformat()} {a["bronnen"][0]["url"]}')
    grens = (vandaag - datetime.timedelta(days=14)).isoformat()
    regels = [l for l in regels if l.split(" ",1)[0] >= grens]
    open(p,"w",encoding="utf-8").write("\n".join(regels)+"\n")
    print(f"Editie {editie} voor {lang} gegenereerd; {sum(len(s.get('artikelen',[])) for s in data['secties'])} items.")

if __name__ == "__main__":
    main()
