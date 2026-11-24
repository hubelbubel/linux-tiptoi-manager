"""Test der Update-Funktion mit simuliertem GitHub (kein Netz, keine echte Installation)."""
import io, json, os, shutil, subprocess, sys, tarfile, tempfile
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, REPO)
HOME = tempfile.mkdtemp(prefix="home_")
os.environ.update(HOME=HOME, XDG_CACHE_HOME=os.path.join(HOME, ".cache"), XDG_CONFIG_HOME=os.path.join(HOME, ".config"))
os.environ.pop("XDG_DATA_HOME", None)
# install.sh prüft python3-gi; im Test durch ein Dummy-python3 ersetzen
fakebin = tempfile.mkdtemp(); open(os.path.join(fakebin, "python3"), "w").write("#!/bin/sh\nexit 0\n")
os.chmod(os.path.join(fakebin, "python3"), 0o755); os.environ["PATH"] = fakebin + os.pathsep + os.environ["PATH"]
import tiptoi_core as c

# version.json im Repo muss zur Programmversion passen
vj = json.load(open(os.path.join(REPO, "version.json"), encoding="utf-8"))
assert vj["version"] == c.APP_VERSION, (vj["version"], c.APP_VERSION)
print("version.json ok:", vj["version"])

print("vergleich:", c.parse_version("1.10.0") > c.parse_version("1.9.3"), c.parse_version("2") == (2, 0, 0))

FILES = ["tiptoi_manager.py", "tiptoi_core.py", "tiptoi-manager.svg", "tiptoi-manager.desktop", "install.sh", "uninstall.sh"]
def archive(version, evil=False):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for f in FILES:
            data = open(os.path.join(REPO, f), "rb").read()
            if f == "tiptoi_core.py":
                data = data.replace(f'APP_VERSION = "{c.APP_VERSION}"'.encode(), f'APP_VERSION = "{version}"'.encode())
            ti = tarfile.TarInfo("linux-tiptoi-manager-main/" + f); ti.size = len(data); ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))
        if evil:
            ti = tarfile.TarInfo("../../boese.txt"); ti.size = 1; t.addfile(ti, io.BytesIO(b"x"))
    return buf.getvalue()

state = {"version": "9.0.0", "evil": False}
def fake_get(url, timeout=25, progress=None, cancel=None):
    if "version.json" in url:
        return json.dumps({"version": state["version"], "date": "2026-11-24", "changes": ["A", "B"]}).encode()
    if "codeload" in url:
        return archive(state["version"], state["evil"])
    raise c.TiptoiError("unbekannt " + url)
c.http_get = fake_get

info = c.check_for_update(c.DEFAULT_CONFIG); print("check:", info.version, info.newer, info.changes)
state["version"] = c.APP_VERSION; print("gleiche Version neuer?", c.check_for_update(c.DEFAULT_CONFIG).newer)
state["version"] = "9.0.0"

# 1) Archiv-Weg (Programm läuft aus ~/.local/share/tiptoi-manager, kein git)
c.INSTALL_DIR = os.path.join(HOME, ".local", "share", "tiptoi-manager")
os.makedirs(c.INSTALL_DIR); c.PROGRAM_DIR = c.INSTALL_DIR
steps = []
path = c.install_update(c.DEFAULT_CONFIG, progress=steps.append)
print("archiv-update ->", path.replace(HOME, "~"), steps)
inst_ver = open(os.path.join(c.INSTALL_DIR, "tiptoi_core.py")).read().split('APP_VERSION = "')[1].split('"')[0]
print("installierte Version:", inst_ver, "| Startmenü:", os.path.exists(os.path.join(HOME, ".local/share/applications/tiptoi-manager.desktop")))
assert inst_ver == "9.0.0"

# 2) Manipuliertes Archiv wird abgewiesen
state["evil"] = True
try:
    c.install_update(c.DEFAULT_CONFIG); print("FEHLER: böses Archiv akzeptiert")
except c.TiptoiError as e:
    print("böses Archiv abgewiesen:", e)
assert not os.path.exists(os.path.join(tempfile.gettempdir(), "boese.txt"))
state["evil"] = False

# 3) git-Weg (Programm läuft aus einem Klon)
origin = tempfile.mkdtemp(prefix="origin_"); clone = os.path.join(tempfile.mkdtemp(), "klon")
for f in FILES: shutil.copy(os.path.join(REPO, f), origin)
g = lambda *a, cwd=origin: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
g("init", "-q", "-b", "main"); g("-c", "user.name=t", "-c", "user.email=t@t", "add", "."); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
subprocess.run(["git", "clone", "-q", origin, clone], check=True)
open(os.path.join(origin, "NEU.txt"), "w").write("neu"); g("add", "."); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v2")
c.PROGRAM_DIR = clone
path = c.install_update(c.DEFAULT_CONFIG)
print("git-update ->", path.endswith("klon/tiptoi_manager.py"), "| neue Datei da:", os.path.exists(os.path.join(clone, "NEU.txt")))
print("UPDATE OK")
