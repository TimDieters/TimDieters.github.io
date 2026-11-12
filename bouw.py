"""Maakt van vissen_raw.json één nette lijst (met soort-groepen) en bouwt vissen.html."""
import base64
import json
import re
from pathlib import Path
from urllib.parse import quote

HIER = Path(__file__).parent

# Volgorde is belangrijk: de eerste regel die past bepaalt de soort.
# Er wordt gezocht in "naam + Latijnse naam" (kleine letters).
SOORT_REGELS = [
    ("Garnalen", r"caridina|garnaal|atya|atyopsis"),
    ("Slakken", r"slak|neritina|anentome|clithon|vittina"),
    ("Kreeften & kikkers", r"kreeft|cambarellus|kikker|hymenochirus"),
    ("Goudvissen", r"goldfish|goudvis|carassius"),
    ("Discusvissen", r"symphysodon|discus"),
    ("Maanvissen", r"pterophyllum|maanvis"),
    ("L-nummers & Ancistrussen", r"^l ?\d{2,3}\b|^lda ?\d+|ancistrus|peckoltia|hypancistrus"),
    ("Dwergcichliden", r"mikrogeophagus|apistogramma|pelvicachromis|laetacara|nannacara|dwergcichlide|antennebaars"),
    ("Cichliden", r"cichl|aulonocara|geophagus|pseudotropheus|haplochromis|hemichromis|heros\b|tropheus|"
                  r"melanochromis|metriaclima|maylandia|lamprologus|altolamprolog|nimbochromis|placidochromis|"
                  r"protomelas|sciaenochromis|labidochromis|cynotilapia|astronotus|acarichthys|andinoa?cara|"
                  r"amatitlania|herotilapia|julidochromis|chindongo"),
    ("Guppen", r"reticulata|gupp|gupman|gupvrouw|\bgup\b"),
    ("Molly's & hoogvinkarpers", r"molly|latipinna|sphenops|velifera|hoogvin"),
    ("Zwaarddragers", r"helleri|hellerii|zwaarddrager"),
    ("Platies", r"maculatus|platy|variatus"),
    ("Corydoras", r"corydoras"),
    ("Botia's", r"botia"),
    ("Modderkruipers", r"pangio|misgurnus|modderkruiper|weeraal"),
    ("Labyrintvissen & gourami's", r"betta|kempvis|gourami|colisa|trichogaster|trichopodus|trichopsis|macropodus|spat\b"),
    ("Danio's", r"danio|tanichthys|devario"),
    ("Rasbora", r"rasbora|trigonostigma|boraras|kegelvlek"),
    ("Barbelen", r"barbus|capoeta|puntius|puntigrus|pethia|barbeel|sumatraan"),
    ("Regenboogvissen", r"melanotaenia|pseudomugil|regenboogvis|regenboogzalm|iriatherina|glossolepis"),
    ("Algeneters", r"otocinclus|algeneter|crossocheilus|gyrinocheilus"),
    ("Tetra's & zalmen", r"hyphessobrycon|hemigrammus|moenkhausia|paracheir|tetra\b|zalm|gymnocorymbus|hasemania|"
                         r"nematobrycon|pristella|thayeria|phenacogrammus|aphyocharax|megalamphodus|holopristis|"
                         r"nannostomus|potloodvis|\brio\b|minor\b"),
    ("Meervallen", r"meerval|wels\b|kryptopterus|pimelodus|synodontis|megalechis|hyalobagrus"),
    ("Killivissen & tandkarpers", r"aplocheil|tand ?karper|oryzias|rijstvis|blauwoog|fundulopanchax|jordanella"),
]
# Categorieën van Aquariumvissenwinkel die we overnemen onder een gezamenlijke naam.
AVW_HERNOEM = {
    "Tetra's": "Tetra's & zalmen", "Zalmen": "Tetra's & zalmen",
    "Gourami": "Labyrintvissen & gourami's", "Labyrinth vissen": "Labyrintvissen & gourami's",
}
AVW_OVERSLAAN = {"Visvoer", "Vismedicijnen"}


def bepaal_soort(naam, latijn, avw_categorie=""):
    if avw_categorie and avw_categorie != "Overige vissen":
        return AVW_HERNOEM.get(avw_categorie, avw_categorie)
    zoek = f"{naam} {latijn}".lower()
    for soort, patroon in SOORT_REGELS:
        if re.search(patroon, zoek):
            return soort
    return "Overige vissen"


def getal(s, grootste=True):
    """'3–4 cm' -> 4.0 ; '5,5' -> 5.5"""
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", s or "")]
    if not nums:
        return None
    return max(nums) if grootste else min(nums)


def veld(tekst, *labels):
    """Zoekt 'Label: waarde' of 'Label\\nwaarde' in een G&D-beschrijving."""
    for label in labels:
        m = re.search(rf"(?im)^\W*{label}[^\n:]*:[ \t]*([^\n]+)", tekst) or \
            re.search(rf"(?im)^\W*{label}[^\n:]*\n([^\n]+)", tekst)
        if m and m.group(1).strip():
            return m.group(1).strip(" .;")
    return ""


def titel(s):
    s = re.sub(r"\s+", " ", s).strip(" /-")
    return s[:1].upper() + s[1:] if s else s


# Oude of verkeerd gespelde Latijnse namen -> de naam die de andere winkel gebruikt,
# zodat dezelfde vis van beide winkels naast elkaar komt te staan.
SYNONIEMEN = {
    "andinocara pulcher": "andinoacara pulcher",
    "aplocheilichthys normani": "poropanchax normani", "aplocheilichtys normani": "poropanchax normani",
    "atya atyopsis": "atyopsis moluccensis", "atya moluccensis": "atyopsis moluccensis",
    "barbus pentazona": "desmopuntius pentazona", "capoeta pentazona": "desmopuntius pentazona",
    "barbus tetrazona": "puntigrus tetrazona", "capoeta tetrazona": "puntigrus tetrazona",
    "barbus titteya": "rohanella titteya", "capoeta titteya": "rohanella titteya", "puntius titteya": "rohanella titteya",
    "barbus panda": "pethia padamya",
    "brachydanio rerio": "danio rerio", "brachydanio frankei": "danio rerio", "danio frankei": "danio rerio",
    "corydoras aeneus": "osteogaster aenea", "corydoras schultzei": "osteogaster aenea",
    "epalzeorhynchus frenatus": "epalzeorhynchos frenatum", "epalzeorhynchos frenatus": "epalzeorhynchos frenatum",
    "hemigrammus rhodostomus": "petitella bleheri", "hemigrammus bleheri": "petitella bleheri",
    "hemigrammus caudovittatus": "psalidodon anisitsi",
    "hyphessobrycon bentosi": "megalamphodus bentosi", "hyphessobrycon megalopterus": "megalamphodus megalopterus",
    "hyphessobrycon sweglesi": "megalamphodus sweglesi", "hyphessobrycon callistus": "megalamphodus eques",
    "hyphessobrycon serpae": "megalamphodus eques", "hyphessobrycon eques": "megalamphodus eques",
    "lamprologus leleupi": "neolamprologus leleupi", "neolamprologus brichardi": "neolamprologus pulcher",
    "melanochromis cyaneorhabdos": "pseudotropheus cyaneorhabdos",
    "metriaclima crabro": "pseudotropheus crabro", "metriaclima lombardoi": "maylandia lombardoi",
    "metriaclima zebra": "maylandia zebra", "pseudotropheus zebra": "maylandia zebra",
    "moenkhausia columbia": "hyphessobrycon columbianus", "moenkhausia pitteri": "makunaima pittieri",
    "moenkhausia pittieri": "makunaima pittieri",
    "neocaridina denticulata": "neocaridina davidi", "neocaridina heteropoda": "neocaridina davidi",
    "paracheirondon axelrodi": "paracheirodon axelrodi",
    "cichlasoma meeki": "thorichthys meeki", "cichlasoma octofasciatum": "rocio octofasciata",
    "pseudotropheus elongatus": "chindongo elongatus", "pseudotropheus saulosi": "chindongo saulosi",
    "puntius conchonius": "pethia conchonius", "puntius denisonii": "sahyadria denisonii",
    "rasbora trillineata": "rasbora trilineata", "rasbora heteromorpha": "trigonostigma heteromorpha",
    "trichogaster trichopterus": "trichopodus trichopterus", "colisa lalia": "trichogaster lalius",
    "colisa chuna": "trichogaster chuna",
    "xipho helleri": "xiphophorus hellerii", "xiphophorus helleri": "xiphophorus hellerii",
    "xipho maculatus": "xiphophorus maculatus",
    "gymnocorymbus ternetzi": "gymnocorymbus ternetzi",
}


def _twee(tekst):
    tekst = re.sub(r"^\s*l(da)?\s*\d+\s*", "", tekst.lower())  # 'L 083 ...' -> zonder L-nummer
    w = re.findall(r"[a-z]+", tekst)
    return " ".join(w[:2])


def sleutel_latijn(latijn, winkeltitel=""):
    """Geeft 'geslacht soort' in kleine letters, met synoniemen gelijkgetrokken."""
    t = _twee(winkeltitel)
    if t in SYNONIEMEN:  # de winkeltitel is betrouwbaarder dan de beschrijving
        return SYNONIEMEN[t]
    k = _twee(latijn)
    return SYNONIEMEN.get(k, k)


def echte_soort(k):
    d = k.split()
    return len(d) == 2 and d[1] not in ("sp", "spp", "cf", "mixed")


def normaliseer(raw):
    vissen = []
    for a in raw["avw"]:
        if a["categorie"] in AVW_OVERSLAAN:
            continue
        e = a["eigenschappen"]
        latijn = e.get("Latijnse naam", "")
        foto = a["fotos"][0] if a["fotos"] else ""
        vissen.append({
            "id": a["id"], "winkel": "Aquariumvissenwinkel", "url": a["url"],
            "naam": a["naam"], "latijn": latijn,
            "soort": bepaal_soort(a["naam"], latijn, a["categorie"]),
            "prijs": float(a["prijs"]) if a["prijs"] else None,
            "voorraad": a["voorraad"] != "OutOfStock",
            "lengte": getal(e.get("Lengte")), "temp": e.get("Temperatuur", ""), "ph": e.get("PH-waarde", ""),
            "herkomst": e.get("Herkomst", ""), "bak": e.get("Aquarium", ""),
            "extra": {k: e[k] for k in ("Familie", "Dieet", "Voeding", "Waterlaag", "Groep") if e.get(k)},
            "tekst": a["beschrijving"],
            "thumb": f"https://aquariumvissenwinkel.nl/_next/image?url={quote(foto, safe='')}&w=640&q=75" if foto else "",
            "fotos": a["fotos"],
        })
    for g in raw["gd"]:
        b = g.get("beschrijving", "")
        delen = [d.strip() for d in g["naam"].split("/") if d.strip()]
        latijn = veld(b, "Wetenschappelijke naam") or (delen[0] if len(delen) > 1 else "")
        latijn = re.sub(r"\s*\((?:voorheen|vaak|soms|synoniem)[^)]*\)", "", latijn)
        # De winkeltitel is "Latijn / Nederlands"; het laatste deel bevat ook de kleurvariant.
        nl = delen[-1] if len(delen) > 1 else g["naam"]
        fotos = g.get("fotos") or ([g["foto_groot"]] if g.get("foto_groot") else [])
        # Eerste maat in cm: uit het veld "(Maximale) grootte", anders de eerste "x–y cm" in de tekst.
        lengte = veld(b, "Maximale grootte", "Grootte", "Maximale lengte", "Lengte", "Formaat")
        m = re.search(r"\d+(?:[.,]\d+)?(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?\s*cm", lengte) or             re.search(r"\d+(?:[.,]\d+)?(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?\s*cm", b)
        lengte = m.group(0) if m else ""
        vissen.append({
            "id": g["id"], "winkel": "G&D Aquaria", "url": g["url"],
            "naam": titel(nl), "latijn": latijn, "titel": g["naam"],
            "soort": bepaal_soort(g["naam"], latijn),
            "prijs": None, "voorraad": True,
            "lengte": getal(lengte) if "cm" in lengte.lower() else None,
            "temp": veld(b, "Temperatuur"), "ph": veld(b, "pH-waarde", "pH"),
            "herkomst": veld(b, "Herkomst"), "bak": veld(b, "Minimale aquariumgrootte", "Aquariumgrootte"),
            "extra": {}, "tekst": b,
            "thumb": fotos[0].replace("/cache/full/", "/cache/article/") if fotos else "",
            "fotos": fotos,
        })
    # Zelfde Latijnse naam bij beide winkels?
    per_latijn = {}
    for v in vissen:
        v["lk"] = sleutel_latijn(v["latijn"], v.get("titel", ""))
        if echte_soort(v["lk"]):
            per_latijn.setdefault(v["lk"], set()).add(v["winkel"])
    for v in vissen:
        v["beide"] = len(per_latijn.get(v["lk"], ())) > 1
    return vissen


def logos():
    """Leest de winkellogo's uit vissen_logos/ en geeft ze terug als data-URL's (pagina blijft 1 bestand)."""
    uit = {}
    for sleutel, bestand, soort in [("gd", "gd_logo.png", "image/png"), ("gdIcon", "gd_icon.png", "image/png"),
                                    ("avw", "avw_logo.svg", "image/svg+xml"), ("avwIcon", "avw_icon.svg", "image/svg+xml")]:
        pad = HIER / "vissen_logos" / bestand
        if pad.exists():
            uit[sleutel] = f"data:{soort};base64," + base64.b64encode(pad.read_bytes()).decode()
    return uit


def push_config():
    """Adres van de Cloudflare Worker + publieke sleutel voor pushmeldingen (push_config.json)."""
    pad = HIER / "push_config.json"
    return json.dumps(json.loads(pad.read_text(encoding="utf-8"))) if pad.exists() else "null"


def main():
    raw = json.loads((HIER / "vissen_raw.json").read_text(encoding="utf-8"))
    vissen = normaliseer(raw)
    (HIER / "vissen.json").write_text(json.dumps(vissen, ensure_ascii=False, indent=1), encoding="utf-8")
    data = json.dumps({"opgehaald": raw["opgehaald"], "vissen": vissen, "logboek": raw.get("logboek", []),
                       "winkelTijd": {"G&D Aquaria": raw.get("gd_opgehaald"), "Aquariumvissenwinkel": raw.get("avw_opgehaald")}}, ensure_ascii=False).replace("</", "<\\/")
    pagina = (HIER / "sjabloon.html").read_text(encoding="utf-8").replace("/*DATA*/null", data) \
        .replace("/*LOGOS*/null", json.dumps(logos())) \
        .replace("/*PUSH*/null", push_config())
    (HIER / "vissen.html").write_text(pagina, encoding="utf-8")
    (HIER / "index.html").write_text(pagina, encoding="utf-8")  # dezelfde pagina, voor GitHub Pages
    print(f"{len(vissen)} vissen -> vissen.html en vissen.json")


if __name__ == "__main__":
    main()
