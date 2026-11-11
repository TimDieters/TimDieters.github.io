"""Haalt alle vissen op van gdaquarium.nl en aquariumvissenwinkel.nl.

Gebruik:
    python scrape.py            # verversen: prijzen/voorraad + alleen nieuwe G&D-vissen (~1-2 min)
    python scrape.py --alles    # ook alle G&D-beschrijvingen opnieuw ophalen (traag, 15+ min)
    python scrape.py --testmelding   # alleen een proefmelding sturen
    python scrape.py --bouw     # alleen vissen.html opnieuw bouwen uit vissen_raw.json
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HIER = Path(__file__).parent
RAW = HIER / "vissen_raw.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
GD_LIJST = "https://www.gdaquarium.nl/c-1956644{}/aquariumvissen-voorraad/"
AVW_SITEMAP = "https://aquariumvissenwinkel.nl/sitemap.xml"


def get(url, pauze=0.25, pogingen=5):
    """Haalt een pagina op; wacht bij 'te veel verzoeken' (429) en probeert opnieuw."""
    for i in range(pogingen):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                time.sleep(pauze)  # rustig aan voor de winkels
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", 0) == 404:  # bestaat niet (bv. voorbij de laatste pagina): niet opnieuw proberen
                return ""
            if i == pogingen - 1:
                print("  mislukt:", url, e)
                return ""
            if getattr(e, "code", 0) == 429:
                wacht = int(e.headers.get("Retry-After") or 0) or 30 * (i + 1)
                print(f"  even wachten ({wacht}s), de winkel remt af...")
                time.sleep(min(wacht, 180))
            else:
                time.sleep(2 * (i + 1))


def tekst(s):
    s = re.sub(r"<(br|/p|/li|/tr|/h\d|hr)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"</t[dh]>", " ", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


# ---------------------------------------------------------------- G&D Aquaria
def gd_lijst():
    items, gezien, n = [], set(), 1
    while n < 60:
        pagina = get(GD_LIJST.format("" if n == 1 else f"-{n}"))
        nieuw = 0
        for li in re.findall(r'<li id="article_(\d+)">(.*?)</li>\s*(?=<li id="article_|</ul>)', pagina, re.S):
            aid, blok = li
            if aid in gezien:
                continue
            gezien.add(aid)
            nieuw += 1
            url = re.search(r'data-product-url="([^"]+)"', blok)
            titel = re.search(r'class="title">([^<]+)<', blok)
            foto = re.search(r'href="(https://cdn\.myonlinestore\.eu/[^"]+/cache/full/[^"?]+)', blok)
            prijs = re.search(r"€\s*([\d.,]+)", tekst(blok))
            kort = re.search(r'<p class="desc">(.*?)</p>', blok, re.S)
            items.append({
                "id": "gd-" + aid,
                "url": url.group(1) if url else "",
                "naam": re.sub(r"\s+", " ", html.unescape(titel.group(1))).strip() if titel else "",
                "foto_groot": foto.group(1) if foto else "",
                "prijs_tekst": prijs.group(1) if prijs else "",
                # begin van de beschrijving zoals het in de lijst staat: hiermee zien we of er iets gewijzigd is
                "lijst_tekst": re.sub(r"\s+", " ", tekst(kort.group(1))) if kort else "",
            })
        print(f"  G&D pagina {n}: {nieuw} vissen")
        if not nieuw:
            break
        n += 1
    return items


def gd_detail(item):
    p = get(item["url"], pauze=0.5)
    item["detail_ok"] = bool(p)
    m = re.search(r'data-tab-content="description">\s*<div[^>]*>(.*?)</div>\s*</div>', p, re.S)
    item["beschrijving"] = tekst(m.group(1)) if m else ""
    m = re.search(r'data-tab-content="specs">(.*?)</div>\s*</div>', p, re.S)
    item["specs_tekst"] = tekst(m.group(1)) if m else ""
    fotos = re.findall(r'(https://cdn\.myonlinestore\.eu/[^"\'?) ]+/cache/full/[^"\'?) ]+)', p)
    item["fotos"] = list(dict.fromkeys(([item["foto_groot"]] if item["foto_groot"] else []) + fotos))
    m = re.search(r'itemprop="price"[^>]*content="([\d.]+)"', p) or re.search(r'"price":\s*"?([\d.]+)', p)
    if m:
        item["prijs_tekst"] = m.group(1)
    return item


# ------------------------------------------------------- Aquariumvissenwinkel
def avw_detail(url):
    p = get(url)
    if not p:
        return {"mislukt": url}  # ophalen lukte niet: straks de vorige gegevens behouden
    for blok in re.findall(r'<script type="application/ld\+json">(.*?)</script>', p, re.S):
        try:
            data = json.loads(blok)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "Product":
                aanbod = d.get("offers") or {}
                if isinstance(aanbod, list):
                    aanbod = aanbod[0] if aanbod else {}
                fotos = d.get("image") or []
                # De sitemap bevat soms ook een oud adres dat doorverwijst naar dezelfde vis.
                # Het adres dat de pagina zelf opgeeft is het echte; daarmee voorkomen we dubbelen.
                url = (d.get("url") or url).rstrip("/")
                return {
                    "id": "avw-" + url.rsplit("/", 1)[-1],
                    "url": url,
                    "naam": d.get("name", ""),
                    "categorie": d.get("category", ""),
                    "beschrijving": d.get("description", ""),
                    "fotos": [fotos] if isinstance(fotos, str) else fotos,
                    "prijs": aanbod.get("price") or aanbod.get("lowPrice"),
                    "voorraad": (aanbod.get("availability") or "").rsplit("/", 1)[-1],
                    "eigenschappen": {e.get("name"): e.get("value") for e in d.get("additionalProperty") or []},
                }
    return None  # geen vis (bv. visvoer): overslaan


def verschil(vorig, nu):
    """Vergelijkt twee runs: welke vissen zijn nieuw, verdwenen, net uitverkocht of weer leverbaar?"""
    import bouw
    a = {v["id"]: v for v in bouw.normaliseer(vorig)}
    b = {v["id"]: v for v in bouw.normaliseer(nu)}

    def mini(v):
        return {k: v.get(k) for k in ("id", "naam", "latijn", "winkel", "url", "thumb", "prijs")}

    w = {
        "nieuw": [mini(v) for i, v in b.items() if i not in a],
        "verwijderd": [mini(v) for i, v in a.items() if i not in b],
        "uitverkocht": [mini(v) for i, v in b.items() if i in a and a[i]["voorraad"] and not v["voorraad"]],
        "terug": [mini(v) for i, v in b.items() if i in a and not a[i]["voorraad"] and v["voorraad"]],
    }
    # Een vis die alleen een ander adres kreeg (zelfde winkel, naam en foto) is niet nieuw of verdwenen.
    zelfde = lambda v: (v["winkel"], v["naam"].lower(), v.get("thumb"))
    hernoemd = {zelfde(v) for v in w["nieuw"]} & {zelfde(v) for v in w["verwijderd"]}
    w["nieuw"] = [v for v in w["nieuw"] if zelfde(v) not in hernoemd]
    w["verwijderd"] = [v for v in w["verwijderd"] if zelfde(v) not in hernoemd]
    print("Wijzigingen sinds", vorig["opgehaald"] + ":")
    for soort, lijst in w.items():
        for v in lijst:
            print(f"  {soort}: {v['naam']} ({v['winkel']})")
    if not any(w.values()):
        print("  geen")
        return None
    return {"datum": nu["opgehaald"], "vorige": vorig["opgehaald"], **w}


def meldingstekst(w):
    """Maakt titel en tekst voor een pushmelding uit een wijziging (zie verschil)."""
    kopjes = [("nieuw", "Nieuw"), ("terug", "Weer op voorraad"), ("uitverkocht", "Net uitverkocht"), ("verwijderd", "Verdwenen")]
    titel = "Vissenlijst: " + ", ".join(f"{len(w[k])} {t.lower()}" for k, t in kopjes if w[k])
    regels = []
    for k, t in kopjes:
        if w[k]:
            namen = [v["naam"] for v in w[k]]
            regels.append(f"{t}: " + ", ".join(namen[:8]) + (f" en nog {len(namen) - 8}" if len(namen) > 8 else ""))
    return titel, "\n".join(regels)


def stuur_melding(w):
    """Stuurt na een run met wijzigingen een melding: naar de site-abonnees (webpush) en/of via ntfy."""
    titel, tekst = meldingstekst(w)
    verstuur(titel, tekst)


def verstuur(titel, tekst):
    site = os.environ.get("VISSEN_URL", "https://timdieters.github.io/")
    stuur_webpush(titel, tekst, site)
    onderwerp = os.environ.get("NTFY_TOPIC", "").strip()
    if onderwerp:  # optioneel: ook via de ntfy-app
        try:
            req = urllib.request.Request(
                "https://ntfy.sh/" + onderwerp, data=tekst.encode("utf-8"), method="POST",
                headers={"Title": titel.encode("ascii", "replace").decode(), "Tags": "fish", "Click": site})
            urllib.request.urlopen(req, timeout=20).read()
            print("ntfy-melding verstuurd:", titel)
        except Exception as e:  # een mislukte melding mag de scrape niet laten mislukken
            print("ntfy-melding versturen mislukt:", e)


def stuur_webpush(titel, tekst, site):
    """Pushmelding naar iedereen die op de site 'Meldingen' heeft aangezet.

    Nodig: push_config.json (adres van de Cloudflare Worker) en de GitHub-secrets
    VAPID_PRIVATE_KEY en PUSH_ADMIN_TOKEN. Ontbreekt er iets, dan gebeurt er niets.
    """
    sleutel = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    token = os.environ.get("PUSH_ADMIN_TOKEN", "").strip()
    pad = HIER / "push_config.json"
    worker = json.loads(pad.read_text(encoding="utf-8")).get("worker", "").rstrip("/") if pad.exists() else ""
    if not (sleutel and token and worker):
        return
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        print("Webpush overgeslagen: pakket 'pywebpush' ontbreekt (pip install pywebpush)")
        return

    def worker_verzoek(pad, data=None):
        req = urllib.request.Request(worker + pad, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Authorization": "Bearer " + token, "User-Agent": UA,
                                              "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    try:
        abonnees = worker_verzoek("/list")
    except Exception as e:  # noqa: BLE001
        print("Webpush: lijst met abonnees ophalen mislukt:", e)
        return
    # Pushdiensten eisen een contactadres van de afzender; dit is het anonieme GitHub-adres.
    contact = os.environ.get("VAPID_CONTACT", "mailto:TimDieters@users.noreply.github.com")
    bericht = json.dumps({"title": titel, "body": tekst, "url": site})
    gelukt, verlopen = 0, []
    for abonnee in abonnees:
        try:
            webpush(subscription_info=abonnee, data=bericht, vapid_private_key=sleutel,
                    vapid_claims={"sub": contact}, ttl=24 * 3600)
            gelukt += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):  # browser heeft de aanmelding ingetrokken
                verlopen.append(abonnee["endpoint"])
            else:
                print("Webpush mislukt voor een abonnee:", status or e)
    if verlopen:
        try:
            worker_verzoek("/remove", {"endpoints": verlopen})
        except Exception as e:  # noqa: BLE001
            print("Webpush: opruimen mislukt:", e)
    print(f"Webpush: {gelukt} van {len(abonnees)} verstuurd, {len(verlopen)} verlopen aanmelding(en) opgeruimd")


def ophalen(alles=False):
    start = time.time()
    vorig = json.loads(RAW.read_text(encoding="utf-8")) if RAW.exists() else None
    oud = {}
    if vorig and not alles:  # eerder opgehaalde G&D-beschrijvingen hergebruiken
        oud = {x["id"]: x for x in vorig["gd"] if x.get("beschrijving")}

    # Aquariumvissenwinkel draait op de achtergrond terwijl G&D (de trage winkel) bezig is.
    print("Aquariumvissenwinkel: sitemap ophalen...")
    urls = [u for u in re.findall(r"<loc>([^<]+)", get(AVW_SITEMAP)) if "/product/" in u]
    print(f"Aquariumvissenwinkel: {len(urls)} productpagina's ophalen (op de achtergrond)...")
    ex = ThreadPoolExecutor(6)
    avw_taken = [ex.submit(avw_detail, u) for u in urls]

    print("G&D Aquaria: lijst ophalen...")
    gd = gd_lijst()
    nieuw, gewijzigd = [], []
    for item in gd:
        bekend = oud.get(item["id"])
        if not bekend:
            nieuw.append(item)
        elif bekend.get("lijst_tekst") and (bekend["lijst_tekst"] != item["lijst_tekst"] or bekend["naam"] != item["naam"]):
            gewijzigd.append(item)  # naam of begin van de beschrijving is anders dan vorige keer
        else:  # vis bestaat al en lijkt ongewijzigd: beschrijving hergebruiken
            item.update({k: bekend[k] for k in ("beschrijving", "specs_tekst", "fotos") if k in bekend})
            if item["foto_groot"] and item["foto_groot"] not in item.get("fotos", []):
                item["fotos"] = [item["foto_groot"]] + item.get("fotos", [])
    weg = [x["naam"] for i, x in oud.items() if i not in {g["id"] for g in gd}]
    print(f"G&D Aquaria: {len(gd)} vissen - {len(nieuw)} nieuw, {len(gewijzigd)} gewijzigd, {len(weg)} verdwenen")
    for label, lijst in (("nieuw", [x["naam"] for x in nieuw]), ("gewijzigd", [x["naam"] for x in gewijzigd]), ("verdwenen", weg)):
        for naam in lijst if oud else []:
            print(f"  {label}: {naam}")
    nieuw += gewijzigd
    if nieuw:
        print(f"  {len(nieuw)} detailpagina's ophalen (~{len(nieuw) * 3 // 60 + 1} min, G&D is traag en blokkeert bij haast)")
    for i, item in enumerate(nieuw, 1):  # een voor een: G&D geeft 429 bij meerdere tegelijk
        gd_detail(item)
        if i % 25 == 0:
            print(f"  {i}/{len(nieuw)}")

    avw_oud = {x["url"]: x for x in vorig["avw"]} if vorig else {}
    avw = []
    for x in (t.result() for t in avw_taken):
        if x and "mislukt" in x:
            x = avw_oud.get(x["mislukt"])
        if x and x["id"] not in {a["id"] for a in avw}:  # zelfde vis via twee adressen: maar een keer opnemen
            avw.append(x)
    ex.shutdown()

    # Veiligheidsrem: als een winkel (bijna) niets teruggeeft is hij onbereikbaar of blokkeert hij ons.
    # Dan niets overschrijven, anders lijken alle vissen "verdwenen".
    for naam, nu, eerder in (("G&D Aquaria", gd, vorig["gd"] if vorig else []), ("Aquariumvissenwinkel", avw, vorig["avw"] if vorig else [])):
        if not nu or len(nu) < len(eerder) / 2:
            sys.exit(f"Gestopt: {naam} gaf {len(nu)} producten terug (vorige keer {len(eerder)}). Er is niets opgeslagen.")

    data = {"opgehaald": time.strftime("%Y-%m-%d %H:%M"), "gd": gd, "avw": avw,
            "logboek": vorig.get("logboek", []) if vorig else []}
    if vorig:
        wijziging = verschil(vorig, data)
        if wijziging:
            data["logboek"] = [wijziging] + data["logboek"][:29]
            stuur_melding(wijziging)
    RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Klaar in {time.time() - start:.0f}s: {len(gd)} + {len(avw)} producten -> {RAW.name}")


if __name__ == "__main__":
    if "--testmelding" in sys.argv:  # alleen een proefmelding sturen, niets ophalen
        verstuur("Vissenlijst: testmelding", "Meldingen werken. Je krijgt bericht als het aanbod verandert.")
        sys.exit()
    if "--bouw" not in sys.argv:
        ophalen(alles="--alles" in sys.argv)
    import bouw
    bouw.main()
