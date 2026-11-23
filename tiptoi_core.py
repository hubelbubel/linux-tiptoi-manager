"""
tiptoi Manager – Kernlogik (ohne Oberfläche).

Enthält:
  * Erkennung angeschlossener tiptoi-Stifte (Gio + /proc/mounts + sysfs)
  * Speicherplatz, installierte Inhalte (.gme / .rav), GME-Header lesen
  * Katalog laden (offizielle tiptoi.csv) und mit Titeln/Beschreibungen anreichern
  * Suchindex mit Live-Vorschlägen, Rechtschreib-Vorschlag ("Meintest du")
  * Herunterladen und sicheres Kopieren auf den Stift

Inoffizielles Werkzeug – nicht mit der Ravensburger AG verbunden.
tiptoi® ist eine eingetragene Marke der Ravensburger AG.
"""
from __future__ import annotations

import csv
import difflib
import html
import io
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser

try:  # Gio ist auf Linux Mint immer vorhanden; für Tests optional
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio  # noqa: E402
except Exception:  # pragma: no cover
    Gio = None

APP_NAME = "tiptoi Manager"
APP_VERSION = "1.0.0"
USER_AGENT = f"tiptoi-manager-linux/{APP_VERSION} (+Linux Mint)"

# --------------------------------------------------------------------------
# Pfade & Konfiguration
# --------------------------------------------------------------------------

def _xdg(env: str, fallback: str) -> str:
    return os.environ.get(env) or os.path.join(os.path.expanduser("~"), fallback)


CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "tiptoi-manager")
CACHE_DIR = os.path.join(_xdg("XDG_CACHE_HOME", ".cache"), "tiptoi-manager")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_FILE = os.path.join(CONFIG_DIR, "suchverlauf.json")

DEFAULT_CONFIG = {
    # Offizielle, öffentlich abrufbare Liste aller Audiodateien (id, version, url, fileName)
    "catalog_url": "https://cdn.ravensburger.de/db/tiptoi.csv",
    # Öffentliche Übersicht mit Titeln, Beschreibungen und Artikelnummern
    "metadata_url": "http://tiptoi.vakat.de/",
    # Vorschaubilder über die Artikelnummer. Platzhalter: {article} / {article5}
    "image_urls": [
        "https://static.images.ravensburger.de/images/produktseiten/210/{article5}.jpg",
        "http://static.images.ravensburger.de/images/produktseiten/210/{article5}.jpg",
    ],
    "catalog_max_age_hours": 24,
    "metadata_max_age_hours": 24 * 7,
    "network_timeout_seconds": 25,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
    except FileNotFoundError:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    except (OSError, ValueError):
        pass
    return cfg


class TiptoiError(Exception):
    """Fehler mit einer für Menschen lesbaren (deutschen) Meldung."""


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def format_size(num: float) -> str:
    """Dezimale Einheiten wie im Dateimanager, deutsches Komma."""
    if num is None:
        return "?"
    units = ["Bytes", "kB", "MB", "GB", "TB"]
    n = float(num)
    i = 0
    while n >= 1000 and i < len(units) - 1:
        n /= 1000.0
        i += 1
    if i == 0:
        return f"{int(n)} Bytes"
    txt = f"{n:.1f}" if n < 100 else f"{n:.0f}"
    return txt.replace(".", ",") + " " + units[i]


def format_version(v: str | None) -> str:
    """20190529 -> 29.05.2019"""
    if v and re.fullmatch(r"\d{8}", v):
        return f"{v[6:8]}.{v[4:6]}.{v[0:4]}"
    return v or ""


def fold(s: str) -> str:
    """Kleinbuchstaben, Akzente/Umlaute vereinfachen (ä->a, ß->ss), Satzzeichen -> Leerzeichen."""
    s = s.replace("ß", "ss").replace("ẞ", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[_\-–—/\\.,:;!?()\[\]{}\"'„“”‚‘’+&*#®™©]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def skey(s: str) -> str:
    """Suchschlüssel: wie fold(), zusätzlich ae/oe/ue == a/o/u (Märchen == Maerchen)."""
    return re.sub(r"([aou])e", r"\1", fold(s))


def _fold_with_map(s: str):
    """Wie fold(), aber zeichenweise mit Rückverweis auf die Originalposition (für Hervorhebungen)."""
    out_chars: list[str] = []
    origin: list[int] = []
    for idx, ch in enumerate(s):
        if ch in "ßẞ":
            rep = "ss"
        else:
            rep = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)).lower()
            if not rep.isalnum():
                rep = " " if rep.strip() == "" or not rep.isalnum() else rep
        for c in rep:
            out_chars.append(c)
            origin.append(idx)
    return "".join(out_chars), origin


def highlight_markup(text: str, query: str) -> str:
    """Gibt Pango-Markup zurück, in dem Wortanfänge, die zur Suche passen, fett sind."""
    if not text:
        return ""
    tokens = [t for t in skey(query).split() if t]
    if not tokens:
        return html.escape(text, quote=False)
    folded, origin = _fold_with_map(text)
    # ae/oe/ue -> a/o/u, Positionszuordnung beibehalten
    keep = [not (ch == "e" and i > 0 and folded[i - 1] in "aou") for i, ch in enumerate(folded)]
    origin = [o for o, k in zip(origin, keep) if k]
    folded = "".join(ch for ch, k in zip(folded, keep) if k)
    marks = [False] * len(text)
    for tok in tokens:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(tok), folded):
            if m.end() > m.start():
                for k in range(origin[m.start()], origin[m.end() - 1] + 1):
                    marks[k] = True
    out = []
    bold = False
    for ch, mk in zip(text, marks):
        if mk and not bold:
            out.append("<b>")
            bold = True
        elif not mk and bold:
            out.append("</b>")
            bold = False
        out.append(html.escape(ch, quote=False))
    if bold:
        out.append("</b>")
    return "".join(out)


def pretty_title_from_filename(name: str) -> str:
    stem = re.sub(r"\.(gme|rav)$", "", name, flags=re.I)
    stem = stem.replace("_", " ").replace("%20", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def norm_filename(name: str) -> str:
    """Schlüssel zum Vergleichen von Dateinamen (Groß/Klein, _, Leerzeichen, Endung egal)."""
    stem = re.sub(r"\.(gme|rav)$", "", urllib.parse.unquote(name or ""), flags=re.I)
    return re.sub(r"[\s_\-]+", "", fold(stem))


def stable_color_index(text: str, n: int = 6) -> int:
    return zlib.crc32((text or "").encode("utf-8")) % n


def initials(title: str) -> str:
    words = [w for w in re.split(r"\s+", title or "") if w and w[0].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def http_get(url: str, timeout: float = 25, progress=None, cancel: threading.Event | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            buf = io.BytesIO()
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise TiptoiError("Abgebrochen.")
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
            return buf.getvalue()
    except TiptoiError:
        raise
    except urllib.error.HTTPError as e:
        raise TiptoiError(f"Server antwortet mit Fehler {e.code} für {url}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        raise TiptoiError(f"Keine Verbindung zu {urllib.parse.urlparse(url).netloc}: {reason}") from e


def _cache_path(*parts: str) -> str:
    p = os.path.join(CACHE_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _cached_fetch(url: str, cache_name: str, max_age_hours: float, timeout: float, force: bool = False):
    """Lädt eine Datei mit Zwischenspeicher. Gibt (bytes, from_cache, cache_mtime) zurück.
    Ist das Netz weg, wird (falls vorhanden) die alte Kopie benutzt."""
    path = _cache_path(cache_name)
    fresh = os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_hours * 3600
    if fresh and not force:
        with open(path, "rb") as f:
            return f.read(), True, os.path.getmtime(path)
    try:
        data = http_get(url, timeout=timeout)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return data, False, time.time()
    except TiptoiError:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read(), True, os.path.getmtime(path)
        raise


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Geräte
# --------------------------------------------------------------------------

KNOWN_USB_MODELS = {
    "04d6:e301": "tiptoi-Stift",
    "04d6:e101": "tiptoi-Stift mit Player",
}
TIPTOI_USB_VENDOR = "04d6"


@dataclass
class UsbInfo:
    vendor: str = ""
    product: str = ""
    manufacturer: str = ""
    product_name: str = ""
    serial: str = ""

    @property
    def usb_id(self) -> str:
        return f"{self.vendor}:{self.product}"


@dataclass
class Device:
    mount_path: str
    label: str
    device_file: str | None = None
    usb: UsbInfo | None = None
    gio_mount: object = None  # Gio.Mount (nur in der Oberfläche benutzt)
    manual: bool = False

    @property
    def display_name(self) -> str:
        if self.usb and self.usb.usb_id in KNOWN_USB_MODELS:
            return KNOWN_USB_MODELS[self.usb.usb_id]
        return "tiptoi-Stift"

    @property
    def key(self) -> str:
        return os.path.realpath(self.mount_path)

    def usage(self):
        u = shutil.disk_usage(self.mount_path)
        return u.total, u.used, u.free


def read_usb_info(device_file: str | None) -> UsbInfo | None:
    """Sucht im sysfs ausgehend von /dev/sdX1 den USB-Elternknoten mit idVendor/idProduct."""
    if not device_file:
        return None
    try:
        name = os.path.basename(os.path.realpath(device_file))
        node = os.path.realpath(os.path.join("/sys/class/block", name))
        for _ in range(12):
            if os.path.exists(os.path.join(node, "idVendor")):
                def rd(fn):
                    try:
                        with open(os.path.join(node, fn), "r", encoding="utf-8", errors="replace") as f:
                            return f.read().strip()
                    except OSError:
                        return ""
                return UsbInfo(rd("idVendor").lower(), rd("idProduct").lower(), rd("manufacturer"),
                               rd("product"), rd("serial"))
            parent = os.path.dirname(node)
            if parent == node or parent in ("/", "/sys"):
                break
            node = parent
    except OSError:
        pass
    return None


def looks_like_tiptoi(path: str) -> bool:
    """Heuristik für Stifte, deren Laufwerk nicht „tiptoi“ heißt."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    lower = [n.lower() for n in names]
    if any(n.endswith(".gme") for n in lower):
        return True
    if any(re.fullmatch(r"update\d*\.upd", n) for n in lower):
        return True
    sys_dir = next((n for n in names if n.lower() == "system"), None)
    if sys_dir:
        try:
            if any("tiptoi" in n.lower() for n in os.listdir(os.path.join(path, sys_dir))):
                return True
        except OSError:
            pass
    return False


def _proc_mounts():
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    dev = parts[0]
                    mnt = parts[1].encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
                    yield dev, mnt, parts[2]
    except OSError:
        return


def device_for_path(path: str) -> str | None:
    best = None
    real = os.path.realpath(path)
    for dev, mnt, _fs in _proc_mounts():
        if real == mnt or real.startswith(mnt.rstrip("/") + "/"):
            if best is None or len(mnt) > len(best[1]):
                best = (dev, mnt)
    return best[0] if best and best[0].startswith("/dev/") else None


def find_devices() -> list[Device]:
    """Alle eingehängten tiptoi-Stifte finden."""
    found: dict[str, Device] = {}
    if Gio is not None:
        try:
            vm = Gio.VolumeMonitor.get()
            for mount in vm.get_mounts():
                root = mount.get_root()
                path = root.get_path() if root else None
                if not path or not os.path.isdir(path):
                    continue
                label = mount.get_name() or os.path.basename(path)
                vol = mount.get_volume()
                dev_file = vol.get_identifier("unix-device") if vol else None
                dev_file = dev_file or device_for_path(path)
                usb = read_usb_info(dev_file)
                is_tt = ("tiptoi" in label.lower()
                         or (usb is not None and usb.vendor == TIPTOI_USB_VENDOR)
                         or looks_like_tiptoi(path))
                if is_tt:
                    d = Device(path, label, dev_file, usb, mount)
                    found[d.key] = d
        except Exception:
            pass
    # Fallback ohne Gio bzw. zusätzliche Mounts
    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    bases = [f"/media/{user}", f"/run/media/{user}", "/media"]
    for dev, mnt, fs in _proc_mounts():
        if not any(mnt.startswith(b + "/") for b in bases):
            continue
        key = os.path.realpath(mnt)
        if key in found:
            continue
        label = os.path.basename(mnt)
        usb = read_usb_info(dev) if dev.startswith("/dev/") else None
        if ("tiptoi" in label.lower() or (usb and usb.vendor == TIPTOI_USB_VENDOR)
                or looks_like_tiptoi(mnt)):
            found[key] = Device(mnt, label, dev if dev.startswith("/dev/") else None, usb, None)
    return sorted(found.values(), key=lambda d: d.mount_path)


def device_from_folder(path: str) -> Device:
    dev = device_for_path(path)
    return Device(path, os.path.basename(path.rstrip("/")) or path, dev, read_usb_info(dev), None, manual=True)


def eject_with_udisks(device_file: str) -> None:
    """Fallback zum Auswerfen ohne Gio (z. B. manuell gewählter Ordner)."""
    if not device_file:
        raise TiptoiError("Unbekanntes Laufwerk – bitte im Dateimanager auswerfen.")
    if not shutil.which("udisksctl"):
        raise TiptoiError("udisksctl wurde nicht gefunden.")
    os.sync()
    r = subprocess.run(["udisksctl", "unmount", "-b", device_file], capture_output=True, text=True)
    if r.returncode != 0 and "not mounted" not in (r.stderr or "").lower():
        raise TiptoiError("Aushängen fehlgeschlagen: " + (r.stderr or r.stdout).strip())
    # Ganzes Laufwerk ausschalten (sdb1 -> sdb)
    whole = re.sub(r"(\d+)$", "", device_file) if re.search(r"sd[a-z]+\d+$", device_file) else device_file
    subprocess.run(["udisksctl", "power-off", "-b", whole], capture_output=True, text=True)


# --------------------------------------------------------------------------
# Installierte Inhalte
# --------------------------------------------------------------------------

@dataclass
class GmeHeader:
    product_id: int | None
    comment: str
    date: str | None


def read_gme_header(path: str) -> GmeHeader | None:
    """Liest Produkt-ID und Erstellungsdatum aus dem GME-Kopf (Format laut tttool-Projekt)."""
    try:
        with open(path, "rb") as f:
            data = f.read(0x200)
    except OSError:
        return None
    if len(data) < 0x30:
        return None
    pid = struct.unpack_from("<I", data, 0x14)[0]
    ln = data[0x20]
    comment = data[0x21:0x21 + ln].decode("ascii", "replace")
    date = data[0x21 + ln:0x21 + ln + 8].decode("ascii", "replace")
    if not re.fullmatch(r"\d{8}", date):
        date = None
    if pid > 10_000_000:
        pid = None
    return GmeHeader(pid, comment, date)


@dataclass
class InstalledItem:
    path: str
    file_name: str
    kind: str  # "Buch/Spiel", "Hörbuch", "Lied"
    size: int
    mtime: float
    header: GmeHeader | None = None
    catalog: "CatalogItem | None" = None

    @property
    def title(self) -> str:
        if self.catalog:
            return self.catalog.title
        return pretty_title_from_filename(self.file_name)

    @property
    def version(self) -> str | None:
        return self.header.date if self.header else None

    @property
    def update_available(self) -> bool:
        if not self.catalog or not self.catalog.version:
            return False
        cv, iv = self.catalog.version, self.version
        if cv and iv and re.fullmatch(r"\d{8}", cv) and re.fullmatch(r"\d{8}", iv):
            return cv > iv
        return False


def _find_child(base: str, name: str) -> str | None:
    try:
        for n in os.listdir(base):
            if n.lower() == name.lower() and os.path.isdir(os.path.join(base, n)):
                return os.path.join(base, n)
    except OSError:
        pass
    return None


def scan_installed(mount_path: str, catalog: "Catalog | None" = None) -> list[InstalledItem]:
    items: list[InstalledItem] = []

    def add(dir_path: str, ext: str, kind: str):
        try:
            entries = os.scandir(dir_path)
        except OSError:
            return
        with entries:
            for e in entries:
                if e.name.startswith(".") or not e.name.lower().endswith(ext):
                    continue
                try:
                    if not e.is_file():
                        continue
                    st = e.stat()
                except OSError:
                    continue
                it = InstalledItem(e.path, e.name, kind, st.st_size, st.st_mtime)
                if ext == ".gme":
                    it.header = read_gme_header(e.path)
                if catalog is not None:
                    it.catalog = catalog.match_installed(it)
                items.append(it)

    add(mount_path, ".gme", "Buch/Spiel")
    for sub, kind in (("stories", "Hörbuch"), ("songs", "Lied")):
        d = _find_child(mount_path, sub)
        if d:
            add(d, ".rav", kind)
    items.sort(key=lambda i: (i.kind != "Buch/Spiel", fold(i.title)))
    return items


def uninstall(item: InstalledItem) -> None:
    try:
        os.remove(item.path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise TiptoiError(f"„{item.title}“ konnte nicht gelöscht werden: {e.strerror}") from e
    os.sync()


# --------------------------------------------------------------------------
# Katalog
# --------------------------------------------------------------------------

@dataclass
class CatalogItem:
    id: str
    version: str
    url: str
    file_name: str  # mit .gme
    title: str
    description: str = ""
    tagline: str = ""
    article: str = ""
    game_id: str = ""
    # Suchfelder
    _title_f: str = field(default="", repr=False)
    _title_words: list = field(default_factory=list, repr=False)
    _desc_f: str = field(default="", repr=False)
    _desc_words: list = field(default_factory=list, repr=False)

    def prepare(self):
        self._title_f = skey(self.title + " " + pretty_title_from_filename(self.file_name))
        self._title_words = self._title_f.split()
        self._desc_f = skey(" ".join([self.tagline, self.description, self.article]))
        self._desc_words = self._desc_f.split()

    def image_urls(self, templates: list[str]) -> list[str]:
        if not self.article or not self.article.isdigit():
            return []
        out = []
        for t in templates:
            try:
                out.append(t.format(article=self.article, article5=self.article.zfill(5)))
            except (KeyError, IndexError, ValueError):
                continue
        return out


def parse_catalog_csv(text: str) -> list[CatalogItem]:
    """Format laut tiptoi.csv:
    CSV file version,Firmware version,...
    <Firmware-Zeile>
    Items._id,Items._version,Items._url,Items._fileName
    150,20190529,https://…/CREATE_Kreative_Bildergeschichten.gme,CREATE_Kreative_Bildergeschichten
    """
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith("items._id"):
            start = i + 1
            break
    items: list[CatalogItem] = []
    seen = set()
    for row in csv.reader(lines[start:]):
        if len(row) < 3:
            continue
        cid, ver, url = row[0].strip(), row[1].strip(), row[2].strip()
        fname = row[3].strip() if len(row) > 3 else ""
        if not url.lower().endswith(".gme"):
            continue  # Firmware, WLAN-Modul usw.
        url_name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        file_name = (fname + ".gme") if fname and not fname.lower().endswith(".gme") else (fname or url_name)
        # Die Datei auf dem Stift sollte so heißen wie auf dem Server
        file_name = url_name or file_name
        key = norm_filename(file_name)
        if key in seen:
            continue
        seen.add(key)
        items.append(CatalogItem(cid, ver, url, file_name, pretty_title_from_filename(fname or file_name)))
    return items


class _LineHTML(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
             "dt", "dd", "pre", "section", "article", "hr", "table", "ul", "ol", "header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, list[str], str]] = []
        self._buf: list[str] = []
        self._hrefs: list[str] = []
        self._tag = ""
        self._skip = 0

    def _flush(self):
        txt = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if txt or self._hrefs:
            self.lines.append((txt, self._hrefs, self._tag))
        self._buf, self._hrefs = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag in self.BLOCK:
            self._flush()
            self._tag = tag
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


_RE_ID = re.compile(r"^\s*ID\s*:?\s*(\d{2,7})\b\s*[-–:|]?\s*(.*)$")
_RE_GAMEID = re.compile(r"Game\s*-?\s*ID\s*:?\s*(\d+)", re.I)
_RE_VERSION = re.compile(r"Version\s*:?\s*(\d{8})", re.I)
_RE_GME = re.compile(r"([^/\\]+\.gme)\b", re.I)
_LABEL_RE = re.compile(r"^(Game\s*-?\s*ID|Version|Download|Datei|File|Link)\b", re.I)


def parse_metadata_html(text: str) -> list[dict]:
    """Tolerantes Auslesen der Übersicht auf tiptoi.vakat.de.
    Einträge beginnen mit einer Zeile „ID <Artikelnummer>“, danach Titel, Untertitel,
    Beschreibung, „Game ID“, „Version“ und ein Link auf die .gme-Datei."""
    p = _LineHTML()
    try:
        p.feed(text)
        p.close()
    except Exception:
        return []
    entries: list[dict] = []
    cur: dict | None = None
    for txt, hrefs, _tag in p.lines:
        m = _RE_ID.match(txt) if txt else None
        if m and not _RE_GAMEID.search(txt):
            if cur:
                entries.append(cur)
            cur = {"article": m.group(1), "title": m.group(2).strip(), "tagline": "", "desc": [],
                   "game_id": "", "version": "", "file": ""}
            continue
        if cur is None:
            continue
        for h in hrefs:
            g = _RE_GME.search(urllib.parse.unquote(h))
            if g:
                cur["file"] = g.group(1)
        if not txt:
            continue
        g = _RE_GAMEID.search(txt)
        if g:
            cur["game_id"] = g.group(1)
        v = _RE_VERSION.search(txt)
        if v:
            cur["version"] = v.group(1)
        f = _RE_GME.search(txt)
        if f and not cur["file"]:
            cur["file"] = f.group(1).strip()
        if g or v or f or _LABEL_RE.match(txt):
            continue
        if not cur["title"]:
            cur["title"] = txt
        elif not cur["tagline"] and len(txt) < 140 and not cur["desc"]:
            cur["tagline"] = txt
        else:
            cur["desc"].append(txt)
    if cur:
        entries.append(cur)
    out = []
    for e in entries:
        if not e["title"]:
            continue
        desc = " ".join(e["desc"]).strip()
        out.append({"article": e["article"], "title": e["title"], "tagline": e["tagline"],
                    "description": desc, "game_id": e["game_id"], "version": e["version"],
                    "file": e["file"]})
    return out


def enrich(items: list[CatalogItem], meta: list[dict]) -> int:
    """Ergänzt Titel/Beschreibung/Artikelnummer. Zuordnung über Dateiname, sonst eindeutige Game-ID."""
    by_file = {}
    by_gid: dict[str, list[dict]] = {}
    for m in meta:
        if m.get("file"):
            by_file.setdefault(norm_filename(m["file"]), m)
        if m.get("game_id"):
            by_gid.setdefault(m["game_id"], []).append(m)
    n = 0
    for it in items:
        m = by_file.get(norm_filename(it.file_name))
        if m is None and it.id in by_gid and len(by_gid[it.id]) == 1:
            m = by_gid[it.id][0]
        if m is None:
            continue
        it.title = m["title"] or it.title
        it.tagline = m.get("tagline", "")
        it.description = m.get("description", "")
        it.article = m.get("article", "")
        it.game_id = m.get("game_id", "")
        n += 1
    return n


class Catalog:
    def __init__(self, items: list[CatalogItem], source_info: str = "", image_templates=None):
        self.items = items
        self.source_info = source_info
        self.image_templates = image_templates or []
        for it in items:
            it.prepare()
        self._by_file = {norm_filename(i.file_name): i for i in items}
        self._by_id: dict[str, list[CatalogItem]] = {}
        for i in items:
            self._by_id.setdefault(i.id, []).append(i)
            if i.game_id:
                self._by_id.setdefault(i.game_id, []).append(i)
        self.index = SearchIndex(items)

    def match_installed(self, inst: InstalledItem) -> CatalogItem | None:
        c = self._by_file.get(norm_filename(inst.file_name))
        if c:
            return c
        if inst.header and inst.header.product_id is not None:
            cands = self._by_id.get(str(inst.header.product_id), [])
            if len(cands) == 1:
                return cands[0]
        return None


def load_catalog(cfg: dict | None = None, force: bool = False) -> Catalog:
    cfg = cfg or load_config()
    timeout = float(cfg.get("network_timeout_seconds", 25))
    data, from_cache, mtime = _cached_fetch(cfg["catalog_url"], "tiptoi.csv",
                                           cfg["catalog_max_age_hours"], timeout, force)
    items = parse_catalog_csv(_decode_text(data))
    if not items:
        raise TiptoiError("Der Katalog ist leer oder hat ein unbekanntes Format.")
    enriched = 0
    try:
        mdata, _, _ = _cached_fetch(cfg["metadata_url"], "metadata.html",
                                    cfg["metadata_max_age_hours"], timeout, force)
        meta = parse_metadata_html(_decode_text(mdata))
        if len(meta) >= 5:
            enriched = enrich(items, meta)
    except TiptoiError:
        pass
    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(mtime))
    info = f"{len(items)} Titel · Stand {when}" + (" (offline)" if from_cache and force else "")
    if enriched:
        info += f" · {enriched} mit Beschreibung"
    return Catalog(items, info, list(cfg.get("image_urls") or []))


def fetch_image(item: CatalogItem, templates: list[str], timeout: float = 15) -> bytes | None:
    """Vorschaubild holen (mit Festplatten-Zwischenspeicher)."""
    if not item.article:
        return None
    path = _cache_path("bilder", f"{item.article}.jpg")
    miss = path + ".fehlt"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as f:
            return f.read()
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < 7 * 86400:
        return None
    for url in item.image_urls(templates):
        try:
            data = http_get(url, timeout=timeout)
        except TiptoiError:
            continue
        if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF":
            with open(path, "wb") as f:
                f.write(data)
            return data
    try:
        open(miss, "w").close()
    except OSError:
        pass
    return None


# --------------------------------------------------------------------------
# Suche
# --------------------------------------------------------------------------

class SearchIndex:
    def __init__(self, items: list[CatalogItem]):
        self.items = items
        vocab: dict[str, int] = {}
        display: dict[str, str] = {}  # Suchschlüssel -> lesbares Wort
        for it in items:
            for w in fold(it.title + " " + pretty_title_from_filename(it.file_name)).split():
                display.setdefault(skey(w), w)
            for w in fold(" ".join([it.tagline, it.description])).split():
                display.setdefault(skey(w), w)
            for w in set(it._title_words):
                vocab[w] = vocab.get(w, 0) + 3
            for w in set(it._desc_words):
                if len(w) > 2:
                    vocab[w] = vocab.get(w, 0) + 1
        self.vocab = vocab
        self.display = display
        self.vocab_list = sorted(vocab, key=lambda w: -vocab[w])

    # -- Ergebnisse ---------------------------------------------------------
    def _score(self, it: CatalogItem, tokens: list[str], phrase: str) -> float:
        score = 0.0
        for tok in tokens:
            best = 0.0
            for w in it._title_words:
                if w == tok:
                    best = max(best, 16)
                elif w.startswith(tok):
                    best = max(best, 11)
                elif len(tok) >= 4 and tok in w:
                    best = max(best, 7)
            if best < 7:
                for w in it._desc_words:
                    if w == tok:
                        best = max(best, 5)
                    elif w.startswith(tok):
                        best = max(best, 4)
                    elif len(tok) >= 5 and tok in w:
                        best = max(best, 3)
            if best == 0 and len(tok) >= 4:
                for w in it._title_words:
                    if abs(len(w) - len(tok)) <= 3 and difflib.SequenceMatcher(None, tok, w).ratio() >= 0.8:
                        best = 4
                        break
            if best == 0:
                return 0.0  # alle Wörter müssen passen
            score += best
        if phrase and len(tokens) > 1 and phrase in it._title_f:
            score += 20
        if it._title_f.startswith(phrase):
            score += 8
        if it.description:
            score += 1  # Einträge mit Beschreibung leicht bevorzugen
        return score

    def search(self, query: str) -> list[CatalogItem]:
        phrase = skey(query)
        tokens = phrase.split()
        if not tokens:
            return []
        scored = []
        for it in self.items:
            s = self._score(it, tokens, phrase)
            if s > 0:
                scored.append((s, it))
        scored.sort(key=lambda x: (-x[0], fold(x[1].title)))
        return [it for _, it in scored]

    # -- Vorschläge ---------------------------------------------------------
    def suggest(self, text: str, history: list[str] | None = None, limit: int = 8) -> list[tuple[str, str]]:
        """Liefert [(Vorschlag, Art)], Art = "verlauf" | "titel" | "wort"."""
        q = skey(text)
        if not q:
            return [(h, "verlauf") for h in (history or [])[:limit]]
        tokens = q.split()
        typed = fold(text).split()
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def push(s: str, kind: str):
            k = skey(s)
            if k and k not in seen and k != q:
                seen.add(k)
                out.append((s, kind))

        for h in history or []:
            if skey(h).startswith(q):
                push(h, "verlauf")
            if len(out) >= 3:
                break
        # Titel, die mit der Eingabe beginnen
        starts = [it for it in self.items if it._title_f.startswith(q)]
        starts.sort(key=lambda it: (len(it.title), it._title_f))
        for it in starts:
            push(it.title, "titel")
            if len(out) >= limit:
                return out
        # Wortergänzung für das letzte Wort (wie bei Google)
        last = tokens[-1]
        prefix = " ".join(typed[:-1])
        words = [self.display.get(w, w) for w in self.vocab_list
                 if w.startswith(last) and w != last and len(w) > 2][:4]
        if text.endswith(" "):
            words = []
        # Titel, in denen alle Wörter vorkommen (letztes als Präfix)
        contains = []
        for it in self.items:
            ws = it._title_words
            if all(any(w.startswith(t) for w in ws) for t in tokens):
                contains.append(it)
        contains.sort(key=lambda it: (len(it.title), it._title_f))
        for w in words[:2]:
            push((prefix + " " + w).strip(), "wort")
        for it in contains:
            push(it.title, "titel")
            if len(out) >= limit:
                break
        return out[:limit]

    def did_you_mean(self, query: str) -> str | None:
        typed = fold(query).split()
        if not typed:
            return None
        changed = False
        new = []
        for word in typed:
            t = skey(word)
            if any(w.startswith(t) for w in self.vocab):
                new.append(word)
                continue
            m = difflib.get_close_matches(t, self.vocab_list, n=1, cutoff=0.72)
            if m:
                new.append(self.display.get(m[0], m[0]))
                changed = True
            else:
                new.append(word)
        if not changed:
            return None
        cand = " ".join(new)
        return cand if self.search(cand) else None


# --------------------------------------------------------------------------
# Suchverlauf
# --------------------------------------------------------------------------

def load_history() -> list[str]:
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            h = json.load(f)
        return [s for s in h if isinstance(s, str)][:30]
    except (OSError, ValueError):
        return []


def add_history(query: str) -> list[str]:
    q = query.strip()
    h = load_history()
    if q:
        h = [q] + [x for x in h if fold(x) != fold(q)]
    h = h[:30]
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return h


def clear_history() -> None:
    try:
        os.remove(HISTORY_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Herunterladen & Übertragen
# --------------------------------------------------------------------------

def ensure_downloaded(item: CatalogItem, progress=None, cancel: threading.Event | None = None,
                      timeout: float = 60) -> str:
    """Lädt die .gme-Datei in den Zwischenspeicher (oder nimmt die vorhandene, wenn gleiche Version)."""
    path = _cache_path("dateien", item.file_name)
    meta_path = path + ".version"
    if os.path.exists(path) and os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                if f.read().strip() == item.version:
                    return path
        except OSError:
            pass
    data = http_get(item.url, timeout=timeout, progress=progress, cancel=cancel)
    if len(data) < 0x40:
        raise TiptoiError(f"Die heruntergeladene Datei für „{item.title}“ ist ungültig.")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    with open(meta_path, "w") as f:
        f.write(item.version or "")
    return path


def copy_to_device(src: str, device: Device, file_name: str, progress=None,
                   cancel: threading.Event | None = None) -> str:
    """Kopiert sicher auf den Stift: erst Platz prüfen, dann als .part schreiben, fsync, umbenennen."""
    if not os.path.isdir(device.mount_path):
        raise TiptoiError("Der Stift ist nicht mehr verbunden.")
    size = os.path.getsize(src)
    dest = os.path.join(device.mount_path, file_name)
    # Gleichnamige Datei (andere Schreibweise) finden – wird ersetzt
    existing = None
    try:
        for n in os.listdir(device.mount_path):
            if norm_filename(n) == norm_filename(file_name) and n.lower().endswith(".gme"):
                existing = os.path.join(device.mount_path, n)
                break
    except OSError as e:
        raise TiptoiError(f"Der Stift kann nicht gelesen werden: {e.strerror}") from e
    old_size = os.path.getsize(existing) if existing else 0
    free = shutil.disk_usage(device.mount_path).free
    needed = size - old_size + 256 * 1024
    if needed > free:
        raise TiptoiError(
            f"Nicht genug Platz auf dem Stift: benötigt {format_size(size)}, frei sind nur "
            f"{format_size(free + old_size)}. Lösche zuerst Inhalte unter „Auf dem Stift“.")
    tmp = os.path.join(device.mount_path, ".tiptoi-manager.part")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise TiptoiError("Abgebrochen.")
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, size)
            fo.flush()
            os.fsync(fo.fileno())
        if existing and os.path.realpath(existing) != os.path.realpath(dest):
            os.remove(existing)
        os.replace(tmp, dest)
        os.sync()
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise TiptoiError(f"Kopieren auf den Stift fehlgeschlagen: {e.strerror or e}") from e
    except TiptoiError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if os.path.getsize(dest) != size:
        raise TiptoiError("Die Datei auf dem Stift ist unvollständig. Bitte erneut versuchen.")
    return dest


def clear_download_cache() -> int:
    d = os.path.join(CACHE_DIR, "dateien")
    total = 0
    if os.path.isdir(d):
        for n in os.listdir(d):
            p = os.path.join(d, n)
            try:
                total += os.path.getsize(p)
                os.remove(p)
            except OSError:
                pass
    return total
