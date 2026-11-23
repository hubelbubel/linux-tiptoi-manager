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

import struct
def gme(path, pid, date):
    comment = b"CHOMPTECH DATA FORMAT CopyRight 2009 Ver2.x.yyyy"
    data = bytearray(0x200)
    struct.pack_into("<I", data, 0x08, 0x238b); struct.pack_into("<I", data, 0x14, pid)
    data[0x20] = len(comment); data[0x21:0x21+len(comment)] = comment
    data[0x21+len(comment):0x21+len(comment)+8] = date.encode()
    open(path, "wb").write(bytes(data) + b"x" * 5000)
