#!/usr/bin/env python3
"""Genereert de dagelijkse Israël-nieuwsbrief via de Anthropic API (met web search)
en werkt index.html, edities/ en gebruikte-items.txt bij. Bedoeld voor GitHub Actions."""
import os, re, sys, json, html as htmllib, datetime, urllib.request

API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
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

def anthropic_call(messages, system):
    """Voert een Messages-request uit met de server-side web search tool en
    handelt pause_turn af tot het model klaar is. Retourneert de finale tekst."""
    url = "https://api.anthropic.com/v1/messages"
    tools = [{"type":"web_search_20250305","name":"web_search","max_uses":8}]
    while True:
        body = {"model":MODEL,"max_tokens":8000,"system":system,
                "messages":messages,"tools":tools}
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
            headers={"x-api-key":API_KEY,"anthropic-version":"2023-06-01",
                     "content-type":"application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.load(r)
        if resp.get("stop_reason") == "pause_turn":
            # Vervolg de beurt: hang de assistant-content aan en herhaal.
            messages.append({"role":"assistant","content":resp["content"]})
            messages.append({"role":"user","content":"Ga verder."})
            continue
        text = "".join(b.get("text","") for b in resp["content"] if b.get("type")=="text")
        return text

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

Zoek met de web search tool naar het belangrijkste Israël-nieuws van de afgelopen 24 uur tot maximaal 5 dagen oud. Gebruik bronnen als Times of Israel, Haaretz, Jerusalem Post, JNS, i24news, CNN, BBC, israelnieuws.nl en israeltoday.nl.

SELECTIEREGELS (strikt):
- GEEN HERHALING: gebruik geen URL of nieuwsfeit dat al voorkomt in de lijst hieronder met eerder gebruikte items. Alleen een wezenlijk nieuwe ontwikkeling mag opnieuw; benoem dan wat nieuw is.
- MAX 5 DAGEN OUD, geef voorrang aan de laatste 24 uur. Twijfel je over de datum, laat het item weg.
- Dedupliceer: hetzelfde feit uit meerdere bronnen = één item met meerdere bronlinks.

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
    m = re.search(r"<<<JSON(.*?)JSON>>>", text, re.S)
    raw = m.group(1).strip() if m else text.strip()
    raw = re.sub(r"^```(?:json)?|```$","",raw,flags=re.M).strip()
    data = json.loads(raw)

    tmpl = open(os.path.join(ROOT,"scripts","template.html"),encoding="utf-8").read()
    page = (tmpl.replace("{{DATUM_LANG}}",esc(lang))
                .replace("{{DATUM_KAP}}",esc(kap))
                .replace("{{EDITIE}}",str(editie))
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
