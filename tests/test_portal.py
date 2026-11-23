"""Test des Serviceportal-Crawlers mit nachgebauten Seiten (kein Netz nötig)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
import tiptoi_core as c
from test_data import CSV

H = "https://service.ravensburger.de"
ROOT = H + "/tiptoi%C2%AE/tiptoi%C2%AE_Audiodateien"
BUECHER = ROOT + "/Audiodateien_tiptoi%C2%AE_B%C3%BCcher"
PUZZLE = ROOT + "/Audiodateien_tiptoi%C2%AE_Puzzles"
QUIZ = ROOT + "/Audiodateien_tiptoi%C2%AE_Wieso%3F_Weshalb%3F_Warum%3F_Quiz"

def page(title, body):
    return f"""<html><head><title>{title} - Serviceportal Ravensburger</title>
<meta property="og:title" content="{title}"/><meta property="og:image" content="{H}/@public/production/site_11910/1528878740-logo.png"/></head>
<body><img src="/@public/production/site_11910/1528878740-logo.png"/>{body}
<a href="/Special:UserLogin?returntotitle=x">Login</a><a href="/Meine_Bestellung">Bestellung</a>
<img src="/@api/deki/files/673/Logo_Brio.png?revision=1"/></body></html>"""

def product(title, img, gme, related=""):
    return page(title, f'<p><a href="{gme}"><img src="{img}"/></a></p><p>Klicken Sie auf das Bild.</p>{related}')

SITE = {
    ROOT: page("tiptoi® Audiodateien", f'''
        <a href="/tiptoi%C2%AE/tiptoi%C2%AE_Audiodateien/Audiodateien_tiptoi%C2%AE_B%C3%BCcher"><img src="/@api/deki/files/1688/mindtouch.page%2523thumbnail?revision=1"/>Bücher</a>
        <a href="{PUZZLE}">Puzzles</a><a href="{QUIZ}">Quiz</a><a href="{ROOT}#top">top</a>'''),
    BUECHER: page("Bücher", f'''<ul><li><a href="{BUECHER}/tiptoi%C2%AE_Audiodatei_Erstes_Englisch_41810">Erstes Englisch</a>
        <li><a href="{BUECHER}/tiptoi%C2%AE_Audiodatei_Bauernhof_32900">Bauernhof</a></ul>'''),
    BUECHER + "/tiptoi%C2%AE_Audiodatei_Erstes_Englisch_41810": product("tiptoi® Audiodatei Erstes Englisch 41810",
        "/@api/deki/files/1786/clipboard_e17.png?revision=1&size=bestfit&width=218&height=255",
        "https://ravensburger.cloud/rvwebsite/rvDE/db/applications/Erstes_Englisch.gme",
        f'<a href="{BUECHER}/tiptoi%C2%AE_Audiodatei_Versteckt_49999">Ähnlich</a>'),
    BUECHER + "/tiptoi%C2%AE_Audiodatei_Bauernhof_32900": product("tiptoi® Audiodatei Wieso? Weshalb? Warum? Bauernhof 32900",
        "/@api/deki/files/2001/clipboard_bh.jpg?revision=1", "https://ravensburger.cloud/rvwebsite/rvDE/db/applications/WWW_Bauernhof.gme"),
    BUECHER + "/tiptoi%C2%AE_Audiodatei_Versteckt_49999": product("tiptoi® Audiodatei Märchen Rotkäppchen 49999",
        "/@api/deki/files/2002/clipboard_rk.png", "https://ravensburger.cloud/rvwebsite/rvDE/db/applications/Maerchen_Rotkaeppchen.gme"),
    PUZZLE: page("Puzzles", f'<a href="{PUZZLE}/tiptoi%C2%AE_Audiodatei_Puzzle_Bauernhof_00066_und_00136">P</a>'),
    PUZZLE + "/tiptoi%C2%AE_Audiodatei_Puzzle_Bauernhof_00066_und_00136": product("tiptoi® Audiodatei Puzzle Bauernhof 00066 und 00136",
        "/@api/deki/files/2003/clipboard_pz.png", "https://ravensburger.cloud/rvwebsite/rvDE/db/applications/Puzzle%20Bauernhof.gme"),
    QUIZ: page("Quiz", f'<a href="{QUIZ}/tiptoi%C2%AE_Audiodatei_Quiz_Sport_49314">Sport</a><a href="{QUIZ}/kaputt">kaputt</a>'),
    QUIZ + "/tiptoi%C2%AE_Audiodatei_Quiz_Sport_49314": product("tiptoi® mini Spielwelt Feuerwehr: Gefahrguteinsatz 00774",
        "/@api/deki/files/2004/clipboard_q.png", "/files/Feuerwehr_Gefahrgut.gme"),
}
calls = []
def fake_get(url, timeout=25, progress=None, cancel=None):
    calls.append(url)
    if url in SITE:
        return SITE[url].encode("utf-8")
    raise c.TiptoiError("404 " + url)
c.http_get = fake_get

print(c.clean_portal_title("tiptoi® Audiodatei Puzzle Bauernhof 00066 und 00136 - Serviceportal Ravensburger"))
print(c.clean_portal_title("tiptoi® Audiodatei Wieso? Weshalb? Warum? Quiz - Sport 49314"))
print(c.clean_portal_title("tiptoi® mini Spielwelt Feuerwehr: Gefahrguteinsatz 00774"))
prog = []
entries = c.crawl_portal(c.DEFAULT_CONFIG, progress=lambda d, t, n: prog.append((d, t, n)))
for e in sorted(entries, key=lambda e: e["file"]):
    print(e["file"], "|", e["title"], "|", e["category"], "|", e["articles"], "|", e["image"][-40:])
print("pages fetched:", len(calls), "| progress last:", prog[-1])
assert len(entries) == 5
assert not any("Special:" in u or "Meine_Bestellung" in u for u in calls)
c.save_portal_cache(entries)
assert not c.portal_cache_stale()
items = c.parse_catalog_csv(CSV)
m, a = c.apply_portal(items, c.load_portal_cache()[0])
print("matched", m, "added", a)
cat = c.Catalog(items, "x", c.DEFAULT_CONFIG["image_urls"])
for q in ["puzzle", "bücher", "englisch", "feuerwehr", "rotkäppchen"]:
    print(q, "->", [(i.title, i.category) for i in cat.index.search(q)])
bh = [i for i in items if i.file_name == "WWW_Bauernhof.gme"][0]
print("WWW:", bh.title, bh.category, bh.article, bh.image_urls([])[0], bh.alt_urls)
# image fetch uses portal URL first
c.http_get = lambda url, timeout=15, **k: b"\x89PNG\r\n\x1a\n" + b"0" * 50 if "clipboard_bh" in url else (_ for _ in ()).throw(c.TiptoiError("x"))
print("image bytes:", len(c.fetch_image(bh, c.DEFAULT_CONFIG["image_urls"]) or b""))
# download falls back to alt url
seen = []
def dl(url, timeout=60, progress=None, cancel=None):
    seen.append(url)
    if "cdn.ravensburger.de" in url: raise c.TiptoiError("Server antwortet mit Fehler 404")
    return b"G" * 500
c.http_get = dl
p = c.ensure_downloaded(bh); print("download via:", seen, os.path.getsize(p))
# whole catalog loading with portal cache
c._cached_fetch = lambda url, name, age, timeout, force=False: ((CSV.encode() if name == "tiptoi.csv" else b"<html></html>"), True, 0)
print("load_catalog:", c.load_catalog(c.DEFAULT_CONFIG).source_info)
print("PORTAL OK")
