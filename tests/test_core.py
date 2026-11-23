import os, sys, struct, tempfile, shutil, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
import importlib, tiptoi_core as c
importlib.reload(c)

CSV = """CSV file version,Firmware version,Firmware checksum,Firmware download address
22020106,6GE027,1872396468,https://cdn.ravensburger.de/db/Firmware-Files/de/27/REV12/Update6E.upd
Items._id,Items._version,Items._url,Items._fileName
0,v201022.1,https://cdn.ravensburger.de/db/Firmware-Files/de/v201022.1/REV-WLAN-MODUL/OTAUpdate.bin,
150,20190529,https://cdn.ravensburger.de/db/applications/CREATE_Kreative_Bildergeschichten.gme,CREATE_Kreative_Bildergeschichten
6,20100408,https://cdn.ravensburger.de/db/applications/Die%20Englisch-Detektive.gme,Die Englisch-Detektive
7,20110217,https://cdn.ravensburger.de/db/applications/Magors_Lesezauber.gme,Magors_Lesezauber
42,20200101,https://cdn.ravensburger.de/db/applications/WWW_Bauernhof.gme,WWW_Bauernhof
43,20210301,https://cdn.ravensburger.de/db/applications/WWW_Unser_Bauernhof_Tiere.gme,WWW_Unser_Bauernhof_Tiere
44,20150101,https://cdn.ravensburger.de/db/applications/Maerchen_Rotkaeppchen.gme,Maerchen_Rotkaeppchen
"""
HTML = """<html><body><h1>Tiptoi GME catalog</h1><p>Content belongs to Ravensburger</p>
<h2>ID 510</h2><h3>Die Englisch-Detektive</h3><p>Setzt euer Englisch ein und fangt Professor Mad!</p>
<p>Ein Englisch-Lernspiel, bei dem die Spieler als Detektive Professor Mad aufhalten.</p>
<ul><li>Für 1-4 Spieler</li></ul>
<p>Game ID: 6</p><p>Version: 20100408</p><p><a href="http://static.tiptoi.com/db/applications/Die Englisch-Detektive.gme">Download</a></p>
<h2>ID 511</h2><h3>Magors Lesezauber</h3><p>Lesen lernen mit Zauberer Magor</p>
<p>Hilf dem tollpatschigen Zauberer Magor, sich auf einen Zauberwettbewerb vorzubereiten.</p>
<p>Game ID: 7</p><p>Version: 20110217</p><p><a href="http://static.tiptoi.com/db/applications/Magors Lesezauber.gme">Magors Lesezauber.gme</a></p>
<h2>ID 32900</h2><h3>Wieso? Weshalb? Warum? Bauernhof</h3><p>Entdecke den Bauernhof</p><p>Kühe, Schweine und Traktoren – alles über das Leben auf dem Bauernhof.</p>
<p>Game ID: 42</p><p>Version: 20200101</p><p><a href="x/WWW_Bauernhof.gme">dl</a></p>
<h2>ID 4</h2><h3>a</h3><h2>ID 5</h2><h3>b</h3>
</body></html>"""

items = c.parse_catalog_csv(CSV)
print("items", len(items), [i.file_name for i in items])
assert len(items) == 6 and items[1].file_name == "Die Englisch-Detektive.gme"
meta = c.parse_metadata_html(HTML)
print("meta", len(meta), meta[0])
n = c.enrich(items, meta); print("enriched", n)
cat = c.Catalog(items, "test", c.DEFAULT_CONFIG["image_urls"])
bh = [i for i in items if i.file_name == "WWW_Bauernhof.gme"][0]
print(bh.title, "|", bh.article, bh.image_urls(cat.image_templates)[0])
idx = cat.index
for q in ["bauernhof", "Bauern", "englisch detektiv", "märchen", "maerchen", "rotkäppchen", "kühe", "bauernhfo", "zauber", "xyz"]:
    print(repr(q), "->", [i.title for i in idx.search(q)], "| dym:", idx.did_you_mean(q))
for q in ["b", "bau", "www b", "ma", "eng", ""]:
    print("suggest", repr(q), idx.suggest(q, history=["bauernhof tiere", "magor"]))
print(c.highlight_markup("Wieso? Weshalb? Warum? Bauernhof & Kühe", "bauern kuhe"))
print(c.highlight_markup("Straße <x>", "strasse"))
print(c.format_size(3_700_000_000), c.format_size(512), c.format_size(23_456_789), c.format_version("20190529"))

# Fake pen
pen = tempfile.mkdtemp(prefix="tiptoi")
def gme(path, pid, date):
    comment = b"CHOMPTECH DATA FORMAT CopyRight 2009 Ver2.x.yyyy"
    data = bytearray(0x200)
    struct.pack_into("<I", data, 0x08, 0x238b); struct.pack_into("<I", data, 0x14, pid)
    data[0x20] = len(comment); data[0x21:0x21+len(comment)] = comment
    data[0x21+len(comment):0x21+len(comment)+8] = date.encode()
    open(path, "wb").write(bytes(data) + b"x" * 5000)
gme(os.path.join(pen, "WWW_Bauernhof.gme"), 42, "20180101")
gme(os.path.join(pen, "Magors Lesezauber.gme"), 7, "20110217")
gme(os.path.join(pen, "Eigenes.gme"), 999, "20240101")
open(os.path.join(pen, "._Eigenes.gme"), "wb").write(b"junk")
os.makedirs(os.path.join(pen, "Stories")); open(os.path.join(pen, "Stories", "Olchi-Detektive - Das Mikado-Komplott.rav"), "wb").write(b"r"*100)
os.makedirs(os.path.join(pen, "system")); open(os.path.join(pen, "system", ".tiptoi.key"), "w").write("k")
print("looks_like", c.looks_like_tiptoi(pen))
inst = c.scan_installed(pen, cat)
for it in inst:
    print("installed:", it.kind, it.title, it.file_name, it.version, it.header and it.header.product_id, "update" if it.update_available else "", it.catalog and it.catalog.file_name)
assert inst[0].header.product_id in (42, 7, 999)

# Copy to device (simulate download cache)
dev = c.device_from_folder(pen)
src = os.path.join(tempfile.mkdtemp(), "WWW_Bauernhof.gme"); gme(src, 42, "20200101")
prog = []
c.copy_to_device(src, dev, "WWW_Bauernhof.gme", progress=lambda d,t: prog.append((d,t)))
inst = c.scan_installed(pen, cat)
print("after update:", [(i.file_name, i.version, i.update_available) for i in inst], prog[-1])
# Different spelling replaced
src2 = os.path.join(tempfile.mkdtemp(), "Magors_Lesezauber.gme"); gme(src2, 7, "20110217")
c.copy_to_device(src2, dev, "Magors_Lesezauber.gme")
print(sorted(os.listdir(pen)))
c.uninstall([i for i in c.scan_installed(pen, cat) if i.file_name == "Eigenes.gme"][0])
print(sorted(os.listdir(pen)))
print("devices:", c.find_devices())
c.add_history("bauernhof"); c.add_history("Magor"); c.add_history("BAUERNHOF"); print(c.load_history())
print("total,used,free", dev.usage(), dev.display_name)
# Not enough space simulation
class FakeUsage: pass
orig = c.shutil.disk_usage
c.shutil.disk_usage = lambda p: type("U",(object,),{"free":100,"total":1000,"used":900})()
try:
    c.copy_to_device(src, dev, "Neu.gme")
except c.TiptoiError as e:
    print("ERR ok:", e)
c.shutil.disk_usage = orig
print("ALL OK")
