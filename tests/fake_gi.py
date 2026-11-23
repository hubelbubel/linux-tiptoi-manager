"""Permissive GTK stand-in to smoke-test Python logic of the GUI (no rendering)."""
import sys, types, html, urllib.parse

class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"): raise AttributeError(name)
        return Dummy
class Dummy(metaclass=_Meta):
    _visible = {}
    def __init__(self, *a, **k): self.__dict__["_props"] = dict(k)
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        return Dummy()
    def __call__(self, *a, **k): return Dummy()
    def __iter__(self): return iter([])
    def __bool__(self): return True
    def __str__(self): return "<dummy>"
    def __format__(self, spec): return "<dummy>"
    def __lt__(self, o): return False
    def __gt__(self, o): return False
    def __getitem__(self, k): return Dummy()
    # widgets
    def get_children(self): return list(self.__dict__.setdefault("_children", []))
    def add(self, w, *a): self.__dict__.setdefault("_children", []).append(w)
    def pack_start(self, w, *a): self.add(w)
    def pack_end(self, w, *a): self.add(w)
    def remove(self, w):
        ch = self.__dict__.setdefault("_children", [])
        if w in ch: ch.remove(w)
    def set_text(self, t): self.__dict__["_text"] = t
    def get_text(self): return self.__dict__.get("_text", "")
    def set_markup(self, t): self.__dict__["_text"] = t
    def set_label(self, t): self.__dict__["_text"] = t
    def get_label(self): return self.__dict__.get("_text", "")
    def set_visible(self, v): self.__dict__["_vis"] = bool(v)
    def show(self): self.__dict__["_vis"] = True
    def hide(self): self.__dict__["_vis"] = False
    def show_all(self): self.__dict__["_vis"] = True
    def get_visible(self): return self.__dict__.get("_vis", False)
    def set_visible_child_name(self, n): self.__dict__["_vcn"] = n
    def get_visible_child_name(self): return self.__dict__.get("_vcn", "")
    def set_sensitive(self, v): self.__dict__["_sens"] = v
    def get_sensitive(self): return self.__dict__.get("_sens", True)
    def connect(self, sig, cb, *a):
        self.__dict__.setdefault("_sig", {}).setdefault(sig, []).append((cb, a)); return 1
    def emit_(self, sig, *args):
        for cb, a in self.__dict__.get("_sig", {}).get(sig, []): cb(self, *args, *a)
    def run(self): return self.__dict__.get("_resp", Gtk_ResponseType_ACCEPT)
    def get_mounts(self): return []
    def child_set_property(self, child, prop, val): self.__dict__.setdefault("_cp", {})[prop] = val
    def get_style_context(self):
        if "_ctx" not in self.__dict__: self.__dict__["_ctx"] = Dummy()
        return self.__dict__["_ctx"]
    def clear(self): self.__dict__["_rows"] = []
    def append(self, *a):
        self.__dict__.setdefault("_rows", []).append(a[0] if len(a) == 1 else a)
    def can_eject(self): return False
    def can_unmount(self): return False

Gtk_ResponseType_ACCEPT = -3
class _RT:
    ACCEPT = -3; CANCEL = -6
def mod(name, **attrs):
    m = types.ModuleType(name)
    def ga(n):
        if n.startswith("__"): raise AttributeError(n)
        return Dummy
    m.__getattr__ = ga
    for k, v in attrs.items(): setattr(m, k, v)
    return m

class GLibError(Exception):
    message = "x"
def idle_add(fn, *a): fn(*a); return 1
GLib = mod("GLib", idle_add=idle_add, timeout_add=lambda *a: 1, timeout_add_seconds=lambda *a: 1,
           source_remove=lambda *a: None, markup_escape_text=lambda s, *a: html.escape(s, quote=False),
           uri_escape_string=lambda s, *a: urllib.parse.quote(s, safe=""), uri_unescape_string=lambda s, *a: urllib.parse.unquote(s),
           set_prgname=lambda *a: None, set_application_name=lambda *a: None, Error=GLibError)
class _VM:
    @staticmethod
    def get(): return Dummy()
Gio = mod("Gio", VolumeMonitor=_VM)
Gtk = mod("Gtk", ResponseType=_RT)
for n in ("Gdk", "GdkPixbuf", "Pango"):
    globals()[n] = mod(n)
repo = types.ModuleType("gi.repository")
for n in ("Gtk", "Gdk", "GdkPixbuf", "Gio", "GLib", "Pango"):
    setattr(repo, n, globals()[n])
gi = types.ModuleType("gi"); gi.require_version = lambda *a: None; gi.repository = repo
sys.modules["gi"] = gi; sys.modules["gi.repository"] = repo
