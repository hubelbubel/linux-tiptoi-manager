#!/usr/bin/env python3
"""
tiptoi Manager für Linux Mint (GTK 3)

  * zeigt den angeschlossenen tiptoi-Stift mit freiem Speicherplatz und wirft ihn sicher aus
  * Google-artige Suche über alle Audiodateien mit Live-Vorschlägen, Vorschaubild, Titel, Beschreibung
  * überträgt Titel auf den Stift, zeigt installierte Inhalte und deinstalliert sie

Inoffizielles Werkzeug – nicht mit der Ravensburger AG verbunden.
tiptoi® ist eine eingetragene Marke der Ravensburger AG.
"""
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))  # auch über Symlink in ~/.local/bin
sys.path.insert(0, HERE)
import tiptoi_core as core  # noqa: E402

APP_ID = "de.tiptoimanager.App"
PAGE_SIZE = 20
COVER = 88

CSS = b"""
.devicebar {
    padding: 10px 18px;
    border-bottom: 1px solid alpha(currentColor, 0.12);
    background-color: alpha(@theme_selected_bg_color, 0.07);
}
.device-name { font-weight: bold; font-size: 115%; }
.dim { opacity: 0.72; }
.small { font-size: 90%; }
.logo { font-size: 52px; font-weight: 800; }
.logo-sub { font-size: 15px; opacity: 0.6; }
.logo-small { font-size: 24px; font-weight: 800; }
entry.bigsearch {
    min-height: 46px;
    border-radius: 24px;
    padding-left: 18px;
    padding-right: 18px;
    font-size: 118%;
    box-shadow: 0 1px 6px alpha(black, 0.18);
}
entry.smallsearch {
    min-height: 38px;
    border-radius: 20px;
    padding-left: 14px;
    padding-right: 14px;
    box-shadow: 0 1px 4px alpha(black, 0.14);
}
button.pill { border-radius: 18px; padding: 6px 18px; }
.result-title { font-size: 128%; }
.results-info { opacity: 0.65; font-size: 92%; }
list.plain, list.plain > row { background-color: transparent; }
row.result { padding: 14px 4px; border-bottom: 1px solid alpha(currentColor, 0.08); }
row.result:hover { background-color: alpha(@theme_selected_bg_color, 0.05); }
.cover { border-radius: 10px; }
.cover-initials { color: white; font-weight: 800; font-size: 26px; }
.cover-0 { background-image: linear-gradient(135deg, #ff9a3c, #ff5e62); }
.cover-1 { background-image: linear-gradient(135deg, #43cea2, #185a9d); }
.cover-2 { background-image: linear-gradient(135deg, #f7971e, #ffd200); }
.cover-3 { background-image: linear-gradient(135deg, #8e2de2, #4a00e0); }
.cover-4 { background-image: linear-gradient(135deg, #00b09b, #96c93d); }
.cover-5 { background-image: linear-gradient(135deg, #ee0979, #ff6a00); }
.cover-image { background-image: none; background-color: transparent; }
.badge { border-radius: 10px; padding: 1px 9px; font-size: 85%; font-weight: bold; }
.badge-ok { background-color: alpha(#2e7d32, 0.15); color: #2e7d32; }
.badge-update { background-color: alpha(#ef6c00, 0.18); color: #e65100; }
.badge-info { background-color: alpha(currentColor, 0.10); }
.toast {
    background-color: rgba(32, 32, 32, 0.94);
    border-radius: 22px;
    padding: 6px 8px 6px 18px;
    margin-top: 14px;
}
.toast label { color: white; }
.toast button { color: white; }
.empty-title { font-size: 140%; font-weight: bold; }
levelbar block { min-height: 8px; }
levelbar block.tt-normal { background-color: @theme_selected_bg_color; border-color: @theme_selected_bg_color; }
levelbar block.tt-warn { background-color: #f57c00; border-color: #f57c00; }
levelbar block.tt-full { background-color: #d32f2f; border-color: #d32f2f; }
"""

LOGO_COLORS = ["#e53935", "#fb8c00", "#43a047", "#1e88e5", "#8e24aa", "#00acc1"]


def esc(s):
    return GLib.markup_escape_text(s or "")


def logo_markup(text="tiptoi"):
    return "".join(f'<span foreground="{LOGO_COLORS[i % len(LOGO_COLORS)]}">{esc(ch)}</span>'
                   for i, ch in enumerate(text))


def label(text="", css=(), xalign=0.0, wrap=False, markup=False, ellipsize=False, lines=-1, max_chars=-1):
    lb = Gtk.Label(xalign=xalign)
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    if wrap:
        lb.set_line_wrap(True)
        lb.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    if lines > 0:
        lb.set_lines(lines)
    if max_chars > 0:
        lb.set_max_width_chars(max_chars)
    for c in css:
        lb.get_style_context().add_class(c)
    return lb


def icon_button(text, icon, css=(), tooltip=None):
    b = Gtk.Button(label=text)
    if icon:
        b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        b.set_always_show_image(True)
    for c in css:
        b.get_style_context().add_class(c)
    if tooltip:
        b.set_tooltip_text(tooltip)
    return b


def set_button(b, text, icon, sensitive=True, css_add=(), css_remove=("suggested-action", "destructive-action")):
    b.set_label(text)
    b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON) if icon else None)
    b.set_always_show_image(bool(icon))
    b.set_sensitive(sensitive)
    ctx = b.get_style_context()
    for c in css_remove:
        ctx.remove_class(c)
    for c in css_add:
        ctx.add_class(c)


def empty_state(icon, title, subtitle=""):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)
    box.set_margin_top(40)
    box.set_margin_bottom(40)
    img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
    img.set_pixel_size(72)
    img.get_style_context().add_class("dim")
    box.pack_start(img, False, False, 0)
    t = label(title, ("empty-title",), xalign=0.5)
    box.pack_start(t, False, False, 0)
    s = label(subtitle, ("dim",), xalign=0.5, wrap=True, max_chars=60)
    s.set_justify(Gtk.Justification.CENTER)
    box.pack_start(s, False, False, 0)
    box.title_label = t
    box.subtitle_label = s
    return box


# --------------------------------------------------------------------------
# Vorschaubilder
# --------------------------------------------------------------------------

class Cover(Gtk.Box):
    """Farbige Kachel mit Initialen; wird durch das Vorschaubild ersetzt, sobald es geladen ist."""

    def __init__(self, title, size=COVER):
        super().__init__()
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.START)
        self._alive = True
        self.connect("destroy", self._on_destroy)
        ctx = self.get_style_context()
        ctx.add_class("cover")
        ctx.add_class(f"cover-{core.stable_color_index(title)}")
        self._color_class = f"cover-{core.stable_color_index(title)}"
        self.initials = label(core.initials(title), ("cover-initials",), xalign=0.5)
        self.initials.set_hexpand(True)
        self.initials.set_vexpand(True)
        self.add(self.initials)

    def _on_destroy(self, *_):
        self._alive = False

    def set_pixbuf(self, pixbuf):
        if not self._alive or pixbuf is None:
            return
        for ch in self.get_children():
            self.remove(ch)
        ctx = self.get_style_context()
        ctx.remove_class(self._color_class)
        ctx.add_class("cover-image")
        img = Gtk.Image.new_from_pixbuf(pixbuf)
        img.set_hexpand(True)
        img.set_vexpand(True)
        self.add(img)
        img.show()


class ImageLoader:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="bilder")
        self.mem = {}
        self.pending = {}

    def request(self, item, templates, callback):
        if item is None or not item.article:
            return
        a = item.article
        if a in self.mem:
            if self.mem[a] is not None:
                callback(self.mem[a])
            return
        if a in self.pending:
            self.pending[a].append(callback)
            return
        self.pending[a] = [callback]
        self.pool.submit(self._work, item, list(templates))

    def _work(self, item, templates):
        pb = None
        try:
            data = core.fetch_image(item, templates)
            if data:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
                if pb is not None:
                    w, h = pb.get_width(), pb.get_height()
                    s = min(COVER / w, COVER / h)
                    pb = pb.scale_simple(max(1, int(w * s)), max(1, int(h * s)), GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            pb = None
        GLib.idle_add(self._done, item.article, pb)

    def _done(self, article, pb):
        self.mem[article] = pb
        for cb in self.pending.pop(article, []):
            if pb is not None:
                try:
                    cb(pb)
                except Exception:
                    pass
        return False


# --------------------------------------------------------------------------
# Listenzeilen
# --------------------------------------------------------------------------

class TransferMixin:
    def _build_progress(self, box):
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress_rev = Gtk.Revealer()
        self.progress_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.progress_rev.add(self.progress)
        self.progress.set_margin_top(6)
        box.pack_start(self.progress_rev, False, False, 0)

    def set_progress(self, frac, text):
        self.progress_rev.set_reveal_child(True)
        if frac is None:
            self.progress.pulse()
        else:
            self.progress.set_fraction(max(0.0, min(1.0, frac)))
        self.progress.set_text(text or "")

    def hide_progress(self):
        self.progress_rev.set_reveal_child(False)


class ResultRow(Gtk.ListBoxRow, TransferMixin):
    def __init__(self, win, item, query):
        super().__init__()
        self.win = win
        self.item = item
        self.key = core.norm_filename(item.file_name)
        self.set_activatable(False)
        self.set_selectable(False)
        self.get_style_context().add_class("result")

        outer = Gtk.Box(spacing=18)
        self.cover = Cover(item.title)
        outer.pack_start(self.cover, False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        col.set_hexpand(True)
        meta = f"{item.file_name}"
        if item.version:
            meta += f"  ·  Version {core.format_version(item.version)}"
        if item.article:
            meta += f"  ·  Art.-Nr. {item.article}"
        col.pack_start(label(meta, ("dim", "small"), ellipsize=True), False, False, 0)
        title = label(core.highlight_markup(item.title, query), ("result-title",), markup=True,
                      wrap=True, max_chars=70)
        col.pack_start(title, False, False, 0)

        desc = " – ".join(x for x in (item.tagline, item.description) if x)
        if desc:
            d = label(core.highlight_markup(desc, query), (), markup=True, wrap=True,
                      ellipsize=True, lines=3, max_chars=95)
        else:
            d = label("Audiodatei für dieses tiptoi-Produkt. Für diesen Titel ist keine Beschreibung verfügbar.",
                      ("dim",), wrap=True, max_chars=95)
        d.set_margin_top(2)
        col.pack_start(d, False, False, 0)

        self.badges = Gtk.Box(spacing=6)
        self.badges.set_margin_top(4)
        col.pack_start(self.badges, False, False, 0)
        self._build_progress(col)
        outer.pack_start(col, True, True, 0)

        self.button = Gtk.Button()
        self.button.set_valign(Gtk.Align.CENTER)
        self.button.get_style_context().add_class("pill")
        self.button.connect("clicked", self._on_click)
        outer.pack_end(self.button, False, False, 0)

        self.add(outer)
        win.images.request(item, win.catalog.image_templates if win.catalog else [], self.cover.set_pixbuf)
        self.update_state()

    def _badge(self, text, css):
        for ch in self.badges.get_children():
            self.badges.remove(ch)
        if text:
            b = label(text, ("badge", css))
            self.badges.pack_start(b, False, False, 0)
            b.show()

    def update_state(self):
        st = self.win.state_for(self.item)
        if st == "laeuft":
            set_button(self.button, "Wird übertragen…", "content-loading-symbolic", sensitive=False)
            t = self.win.transfers.get(self.key, {})
            self.set_progress(t.get("frac"), t.get("text", "Wartet…"))
            self._badge("", "")
            return
        self.hide_progress()
        if st == "installiert":
            set_button(self.button, "Auf dem Stift", "emblem-ok-symbolic", sensitive=False)
            self._badge("✓ Installiert", "badge-ok")
        elif st == "update":
            set_button(self.button, "Aktualisieren", "view-refresh-symbolic", css_add=("suggested-action",))
            self._badge("Neue Version verfügbar", "badge-update")
        elif st == "kein_stift":
            set_button(self.button, "Auf den Stift", "document-send-symbolic", sensitive=False)
            self.button.set_tooltip_text("Kein tiptoi-Stift verbunden")
            self._badge("", "")
        else:
            set_button(self.button, "Auf den Stift", "document-send-symbolic", css_add=("suggested-action",))
            self.button.set_tooltip_text(f"„{self.item.title}“ herunterladen und auf den Stift übertragen")
            self._badge("", "")

    def _on_click(self, *_):
        self.win.install(self.item)


class InstalledRow(Gtk.ListBoxRow, TransferMixin):
    def __init__(self, win, inst):
        super().__init__()
        self.win = win
        self.inst = inst
        self.key = core.norm_filename(inst.file_name)
        self.set_activatable(False)
        self.set_selectable(False)
        self.get_style_context().add_class("result")

        outer = Gtk.Box(spacing=18)
        self.cover = Cover(inst.title, size=64)
        outer.pack_start(self.cover, False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        col.set_hexpand(True)
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(label(f"<b>{esc(inst.title)}</b>", markup=True, wrap=True, max_chars=70), False, False, 0)
        parts = [inst.kind, inst.file_name, core.format_size(inst.size)]
        if inst.version:
            parts.append("Version " + core.format_version(inst.version))
        if inst.header and inst.header.product_id is not None:
            parts.append(f"Produkt-ID {inst.header.product_id}")
        col.pack_start(label("  ·  ".join(parts), ("dim", "small"), ellipsize=True), False, False, 0)

        badges = Gtk.Box(spacing=6)
        if inst.update_available:
            badges.pack_start(label(f"Update verfügbar ({core.format_version(inst.catalog.version)})",
                                    ("badge", "badge-update")), False, False, 0)
        elif inst.kind == "Buch/Spiel" and inst.catalog is None:
            badges.pack_start(label("Nicht im Katalog (z. B. eigene Datei)", ("badge", "badge-info")), False, False, 0)
        if badges.get_children():
            badges.set_margin_top(3)
            col.pack_start(badges, False, False, 0)
        self._build_progress(col)
        outer.pack_start(col, True, True, 0)

        btns = Gtk.Box(spacing=6)
        btns.set_valign(Gtk.Align.CENTER)
        if inst.update_available:
            self.update_btn = icon_button("Aktualisieren", "view-refresh-symbolic", ("suggested-action", "pill"))
            self.update_btn.connect("clicked", lambda *_: self.win.install(self.inst.catalog))
            btns.pack_start(self.update_btn, False, False, 0)
        else:
            self.update_btn = None
        self.remove_btn = icon_button("Deinstallieren", "user-trash-symbolic", ("destructive-action", "pill"),
                                      tooltip="Vom Stift löschen")
        self.remove_btn.connect("clicked", lambda *_: self.win.confirm_uninstall(self.inst))
        btns.pack_start(self.remove_btn, False, False, 0)
        outer.pack_end(btns, False, False, 0)

        self.add(outer)
        if inst.catalog:
            win.images.request(inst.catalog, win.catalog.image_templates if win.catalog else [],
                               self.cover.set_pixbuf)
        self.update_state()

    def update_state(self):
        busy = self.key in self.win.transfers
        self.remove_btn.set_sensitive(not busy)
        if self.update_btn:
            self.update_btn.set_sensitive(not busy)
        if busy:
            t = self.win.transfers[self.key]
            self.set_progress(t.get("frac"), t.get("text", "Wartet…"))
        else:
            self.hide_progress()


# --------------------------------------------------------------------------
# Hauptfenster
# --------------------------------------------------------------------------

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=core.APP_NAME)
        self.set_default_size(1040, 760)
        self.set_icon_name("tiptoi-manager")

        self.cfg = core.load_config()
        self.catalog = None
        self.catalog_error = None
        self.history = core.load_history()
        self.devices = []
        self.device = None
        self.manual_device = None
        self.installed = []
        self.inst_by_file = {}
        self.inst_by_catalog = {}
        self.transfers = {}
        self.transfer_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uebertragung")
        self.images = ImageLoader()
        self.result_rows = {}
        self.installed_rows = {}
        self.results = []
        self.shown = 0
        self.current_query = ""
        self.pending_query = None
        self._suppress = False
        self._dev_timer = 0
        self._inst_gen = 0
        self._toast_timer = 0
        self._last_post = {}
        self._ejecting = False

        self._build_actions()
        self._build_ui()

        self.vm = Gio.VolumeMonitor.get()
        for sig in ("mount-added", "mount-removed", "mount-changed"):
            self.vm.connect(sig, self.schedule_device_refresh)
        self.connect("delete-event", self._on_delete)

        self._just_ejected = 0.0
        self.show_all()
        self._post_show()
        self.refresh_devices()
        self.load_catalog()

    # ---------------------------------------------------------------- Aufbau
    def _build_actions(self):
        def add(name, cb, accels=None):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
            if accels:
                self.get_application().set_accels_for_action(f"win.{name}", accels)

        add("focus-search", lambda *_: self.focus_search(), ["<Control>f", "<Control>l"])
        add("refresh", lambda *_: self.refresh_devices(), ["F5"])
        add("choose-folder", lambda *_: self.choose_folder())
        add("reload-catalog", lambda *_: self.load_catalog(force=True))
        add("clear-cache", lambda *_: self.clear_cache())
        add("clear-history", lambda *_: self.clear_history())
        add("show-installed", lambda *_: self.main_stack.set_visible_child_name("installed"), ["<Control>2"])
        add("show-search", lambda *_: self.main_stack.set_visible_child_name("search"), ["<Control>1"])

    def _build_ui(self):
        # Kopfleiste
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_title(core.APP_NAME)
        self.set_titlebar(hb)

        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.main_stack)
        hb.set_custom_title(switcher)

        menu = Gio.Menu()
        sec1 = Gio.Menu()
        sec1.append("Geräte neu suchen", "win.refresh")
        sec1.append("Stift-Ordner manuell wählen…", "win.choose-folder")
        menu.append_section(None, sec1)
        sec2 = Gio.Menu()
        sec2.append("Katalog neu laden", "win.reload-catalog")
        sec2.append("Suchverlauf löschen", "win.clear-history")
        sec2.append("Download-Zwischenspeicher leeren", "win.clear-cache")
        menu.append_section(None, sec2)
        sec3 = Gio.Menu()
        sec3.append("Über tiptoi Manager", "app.about")
        sec3.append("Beenden", "app.quit")
        menu.append_section(None, sec3)
        mb = Gtk.MenuButton()
        mb.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        mb.set_menu_model(menu)
        hb.pack_end(mb)

        # Inhalt mit Overlay für Hinweise ("Toasts")
        overlay = Gtk.Overlay()
        self.add(overlay)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.add(root)
        root.pack_start(self._build_device_bar(), False, False, 0)
        root.pack_start(self.main_stack, True, True, 0)

        self.main_stack.add_titled(self._build_search_page(), "search", "Suchen")
        self.installed_page = self._build_installed_page()
        self.main_stack.add_titled(self.installed_page, "installed", "Auf dem Stift")

        self.toast_rev = Gtk.Revealer()
        self.toast_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.toast_rev.set_halign(Gtk.Align.CENTER)
        self.toast_rev.set_valign(Gtk.Align.START)
        tbox = Gtk.Box(spacing=8)
        tbox.get_style_context().add_class("toast")
        self.toast_label = label("", wrap=True, max_chars=70)
        self.toast_label.set_valign(Gtk.Align.CENTER)
        tbox.pack_start(self.toast_label, True, True, 0)
        tclose = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        tclose.set_relief(Gtk.ReliefStyle.NONE)
        tclose.connect("clicked", lambda *_: self.toast_rev.set_reveal_child(False))
        tbox.pack_start(tclose, False, False, 0)
        self.toast_rev.add(tbox)
        overlay.add_overlay(self.toast_rev)

    def _build_device_bar(self):
        bar = Gtk.Box(spacing=14)
        bar.get_style_context().add_class("devicebar")

        self.dev_icon = Gtk.Image()
        self.dev_icon.set_pixel_size(42)
        bar.pack_start(self.dev_icon, False, False, 0)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_valign(Gtk.Align.CENTER)
        self.dev_name = label("", ("device-name",), ellipsize=True)
        self.dev_details = label("", ("dim", "small"), ellipsize=True)
        info.pack_start(self.dev_name, False, False, 0)
        info.pack_start(self.dev_details, False, False, 0)
        bar.pack_start(info, True, True, 0)

        self.dev_combo = Gtk.ComboBoxText()
        self.dev_combo.set_valign(Gtk.Align.CENTER)
        self._combo_handler = self.dev_combo.connect("changed", self._on_combo_changed)
        bar.pack_start(self.dev_combo, False, False, 0)

        self.storage_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.storage_box.set_valign(Gtk.Align.CENTER)
        self.storage_box.set_size_request(260, -1)
        self.level = Gtk.LevelBar()
        self.level.set_min_value(0.0)
        self.level.set_max_value(1.0)
        for off in ("low", "high", "full"):
            self.level.remove_offset_value(off)
        self.level.add_offset_value("tt-normal", 0.85)
        self.level.add_offset_value("tt-warn", 0.95)
        self.level.add_offset_value("tt-full", 1.0)
        self.storage_label = label("", ("small",), markup=True)
        self.storage_box.pack_start(self.storage_label, False, False, 0)
        self.storage_box.pack_start(self.level, False, False, 0)
        self.level.show()
        self.storage_label.show()
        bar.pack_start(self.storage_box, False, False, 0)

        self.eject_btn = icon_button("Auswerfen", "media-eject-symbolic", ("pill",),
                                     tooltip="Stift sicher auswerfen")
        self.eject_btn.set_valign(Gtk.Align.CENTER)
        self.eject_btn.connect("clicked", self.on_eject)
        bar.pack_start(self.eject_btn, False, False, 0)
        return bar

    def _make_search_entry(self, big):
        e = Gtk.SearchEntry()
        e.set_placeholder_text("tiptoi-Bücher, Spiele und Puzzles durchsuchen")
        e.get_style_context().add_class("bigsearch" if big else "smallsearch")
        # Wichtig: "changed" vor der Vervollständigung verbinden, damit die Liste schon aktuell ist
        e.connect("changed", self._on_entry_changed)
        e.connect("activate", lambda en: self.run_search(en.get_text()))
        store = Gtk.ListStore(str, str, str)  # Text, Markup, Symbol
        comp = Gtk.EntryCompletion()
        comp.set_model(store)
        comp.set_match_func(lambda *a: True)
        comp.set_minimum_key_length(1)
        comp.set_popup_single_match(True)
        comp.set_inline_completion(False)
        ic = Gtk.CellRendererPixbuf()
        ic.set_padding(6, 4)
        comp.pack_start(ic, False)
        comp.add_attribute(ic, "icon-name", 2)
        tx = Gtk.CellRendererText()
        tx.set_property("ellipsize", Pango.EllipsizeMode.END)
        comp.pack_start(tx, True)
        comp.add_attribute(tx, "markup", 1)
        comp.connect("match-selected", self._on_match_selected)
        e.set_completion(comp)
        e.store = store
        return e

    def _build_search_page(self):
        self.search_stack = Gtk.Stack()
        self.search_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.search_stack.set_transition_duration(220)

        # Startseite (wie bei Google: Logo + großes Suchfeld)
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        home.set_valign(Gtk.Align.CENTER)
        home.set_halign(Gtk.Align.CENTER)
        home.set_margin_bottom(60)
        logo = label(logo_markup(), ("logo",), xalign=0.5, markup=True)
        home.pack_start(logo, False, False, 0)
        sub = label("Bücher · Spiele · Puzzles · Globus", ("logo-sub",), xalign=0.5)
        home.pack_start(sub, False, False, 0)
        self.home_entry = self._make_search_entry(True)
        self.home_entry.set_size_request(620, -1)
        home.pack_start(self.home_entry, False, False, 0)
        btns = Gtk.Box(spacing=10)
        btns.set_halign(Gtk.Align.CENTER)
        b1 = Gtk.Button(label="tiptoi-Suche")
        b1.get_style_context().add_class("pill")
        b1.connect("clicked", lambda *_: self.run_search(self.home_entry.get_text()))
        b2 = Gtk.Button(label="Auf gut Glück!")
        b2.get_style_context().add_class("pill")
        b2.connect("clicked", lambda *_: self.lucky())
        btns.pack_start(b1, False, False, 0)
        btns.pack_start(b2, False, False, 0)
        home.pack_start(btns, False, False, 0)
        status = Gtk.Box(spacing=8)
        status.set_halign(Gtk.Align.CENTER)
        self.cat_spinner = Gtk.Spinner()
        self.cat_status = label("", ("dim", "small"), xalign=0.5, wrap=True, max_chars=80)
        self.cat_retry = Gtk.Button(label="Erneut versuchen")
        self.cat_retry.connect("clicked", lambda *_: self.load_catalog(force=True))
        status.pack_start(self.cat_spinner, False, False, 0)
        status.pack_start(self.cat_status, False, False, 0)
        status.pack_start(self.cat_retry, False, False, 0)
        home.pack_start(status, False, False, 0)
        self.search_stack.add_named(home, "home")

        # Ergebnisseite
        res = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.Box(spacing=18)
        top.set_margin_top(14)
        top.set_margin_bottom(12)
        top.set_margin_start(28)
        top.set_margin_end(28)
        logo_btn = Gtk.Button()
        logo_btn.set_relief(Gtk.ReliefStyle.NONE)
        logo_btn.add(label(logo_markup(), ("logo-small",), markup=True))
        logo_btn.set_tooltip_text("Zur Startseite")
        logo_btn.connect("clicked", lambda *_: self.go_home())
        top.pack_start(logo_btn, False, False, 0)
        self.results_entry = self._make_search_entry(False)
        self.results_entry.set_size_request(560, -1)
        self.results_entry.set_valign(Gtk.Align.CENTER)
        top.pack_start(self.results_entry, False, False, 0)
        res.pack_start(top, False, False, 0)
        res.pack_start(Gtk.Separator(), False, False, 0)

        self.results_scroller = Gtk.ScrolledWindow()
        self.results_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_margin_start(130)
        col.set_margin_end(40)
        col.set_margin_top(10)
        col.set_margin_bottom(30)
        self.results_info = label("", ("results-info",))
        col.pack_start(self.results_info, False, False, 0)
        self.dym_label = label("", markup=True)
        self.dym_label.connect("activate-link", self._on_dym)
        col.pack_start(self.dym_label, False, False, 0)
        self.results_list = Gtk.ListBox()
        self.results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.results_list.get_style_context().add_class("plain")
        col.pack_start(self.results_list, False, False, 0)
        self.no_results = empty_state("edit-find-symbolic", "Keine Treffer",
                                      "Prüfe die Schreibweise oder versuche allgemeinere Begriffe, "
                                      "z. B. „Bauernhof“, „Zahlen“ oder „Englisch“.")
        col.pack_start(self.no_results, False, False, 0)
        self.more_btn = Gtk.Button(label="Weitere Ergebnisse anzeigen")
        self.more_btn.get_style_context().add_class("pill")
        self.more_btn.set_halign(Gtk.Align.CENTER)
        self.more_btn.set_margin_top(14)
        self.more_btn.connect("clicked", lambda *_: self.show_more())
        col.pack_start(self.more_btn, False, False, 0)
        self.results_scroller.add(col)
        res.pack_start(self.results_scroller, True, True, 0)
        self.search_stack.add_named(res, "results")
        return self.search_stack

    def _build_installed_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.Box(spacing=12)
        top.set_margin_top(14)
        top.set_margin_bottom(12)
        top.set_margin_start(28)
        top.set_margin_end(28)
        self.inst_summary = label("", ("device-name",))
        top.pack_start(self.inst_summary, True, True, 0)
        self.update_all_btn = icon_button("Alle aktualisieren", "view-refresh-symbolic", ("pill",))
        self.update_all_btn.connect("clicked", lambda *_: self.update_all())
        top.pack_start(self.update_all_btn, False, False, 0)
        self.inst_filter = Gtk.SearchEntry()
        self.inst_filter.set_placeholder_text("Inhalte filtern")
        self.inst_filter.set_size_request(260, -1)
        self.inst_filter.connect("search-changed", lambda *_: self.inst_list.invalidate_filter())
        top.pack_start(self.inst_filter, False, False, 0)
        page.pack_start(top, False, False, 0)
        page.pack_start(Gtk.Separator(), False, False, 0)

        self.inst_stack = Gtk.Stack()
        self.inst_stack.add_named(empty_state("drive-removable-media-symbolic", "Kein tiptoi-Stift verbunden",
                                              "Schalte den Stift ein und verbinde ihn mit dem USB-Kabel. "
                                              "Er erscheint dann automatisch hier."), "nodevice")
        self.inst_stack.add_named(empty_state("folder-open-symbolic", "Noch keine Inhalte auf dem Stift",
                                              "Suche ein Buch oder Spiel und übertrage es mit „Auf den Stift“."),
                                  "empty")
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.inst_list = Gtk.ListBox()
        self.inst_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.inst_list.get_style_context().add_class("plain")
        self.inst_list.set_margin_start(28)
        self.inst_list.set_margin_end(28)
        self.inst_list.set_margin_bottom(24)
        self.inst_list.set_filter_func(self._inst_filter_func)
        sc.add(self.inst_list)
        self.inst_stack.add_named(sc, "list")
        page.pack_start(self.inst_stack, True, True, 0)
        return page

    def _post_show(self):
        # Elemente, die erst bei Bedarf erscheinen
        for w in (self.dym_label, self.no_results, self.more_btn, self.cat_retry, self.cat_spinner,
                  self.update_all_btn, self.dev_combo, self.storage_box, self.eject_btn):
            w.hide()
        self.search_stack.set_visible_child_name("home")
        self.update_device_bar()
        self.render_installed()
        self.home_entry.grab_focus()

    # ------------------------------------------------------------- Hinweise
    def toast(self, text, seconds=4):
        self.toast_label.set_text(text)
        self.toast_rev.set_reveal_child(True)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)

        def hide():
            self.toast_rev.set_reveal_child(False)
            self._toast_timer = 0
            return False
        self._toast_timer = GLib.timeout_add_seconds(seconds, hide)

    def error_dialog(self, title, text):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.CLOSE, text=title)
        d.format_secondary_text(text)
        d.run()
        d.destroy()

    # -------------------------------------------------------------- Katalog
    def load_catalog(self, force=False):
        self.cat_spinner.start()
        self.cat_spinner.show()
        self.cat_retry.hide()
        self.cat_status.set_text("Katalog wird geladen …")

        def work():
            try:
                cat = core.load_catalog(self.cfg, force)
                GLib.idle_add(self._catalog_loaded, cat, None)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._catalog_loaded, None, e)
        threading.Thread(target=work, daemon=True).start()

    def _catalog_loaded(self, cat, err):
        self.cat_spinner.stop()
        self.cat_spinner.hide()
        if err is not None:
            self.catalog_error = err
            self.cat_status.set_text(f"Katalog nicht verfügbar: {err}")
            self.cat_retry.show()
            if self.catalog is None:
                self.toast("Der Katalog konnte nicht geladen werden. Bist du online?")
            return False
        self.catalog = cat
        self.catalog_error = None
        self.cat_status.set_text(f"Durchsuche {cat.source_info} · Enter drücken zum Suchen")
        self.refresh_installed()
        if self.pending_query:
            q, self.pending_query = self.pending_query, None
            self.run_search(q)
        elif self.current_query:
            self.run_search(self.current_query, add_history=False)
        return False

    # ---------------------------------------------------------------- Suche
    def focus_search(self):
        self.main_stack.set_visible_child_name("search")
        entry = self.results_entry if self.search_stack.get_visible_child_name() == "results" else self.home_entry
        entry.grab_focus()

    def _set_entries(self, text):
        self._suppress = True
        for e in (self.home_entry, self.results_entry):
            if e.get_text() != text:
                e.set_text(text)
            e.store.clear()
        self._suppress = False

    def _on_entry_changed(self, entry):
        if self._suppress:
            return
        store = entry.store
        store.clear()
        if not self.catalog:
            return
        text = entry.get_text()
        if not text.strip():
            return
        for s, kind in self.catalog.index.suggest(text, self.history, 8):
            if s.lower().startswith(text.lower()):
                markup = esc(s[:len(text)]) + "<b>" + esc(s[len(text):]) + "</b>"
            else:
                markup = core.highlight_markup(s, text)
            icon = "document-open-recent-symbolic" if kind == "verlauf" else "edit-find-symbolic"
            store.append([s, markup, icon])

    def _on_match_selected(self, completion, model, it):
        self.run_search(model[it][0])
        return True

    def _on_dym(self, _label, uri):
        self.run_search(GLib.uri_unescape_string(uri[len("suche:"):], None) or "")
        return True

    def go_home(self):
        self.current_query = ""
        self._set_entries("")
        self.search_stack.set_visible_child_name("home")
        self.home_entry.grab_focus()

    def lucky(self):
        if not self.catalog or not self.catalog.items:
            self.toast("Der Katalog wird noch geladen …")
            return
        with_desc = [i for i in self.catalog.items if i.description] or self.catalog.items
        self.run_search(random.choice(with_desc).title)

    def run_search(self, query, add_history=True):
        query = (query or "").strip()
        if not query:
            return
        self.main_stack.set_visible_child_name("search")
        if not self.catalog:
            self.pending_query = query
            self.toast("Der Katalog wird noch geladen – die Suche startet gleich automatisch.")
            return
        t0 = time.perf_counter()
        results = self.catalog.index.search(query)
        dt = time.perf_counter() - t0
        if add_history:
            self.history = core.add_history(query)
        self.current_query = query
        self.results = results
        self.shown = 0
        self._set_entries(query)

        for ch in self.results_list.get_children():
            self.results_list.remove(ch)
            ch.destroy()
        self.result_rows = {}

        n = len(results)
        if n:
            word = "Ergebnis" if n == 1 else "Ergebnisse"
            self.results_info.set_text(f"Ungefähr {n} {word} ({dt:.2f} Sekunden)".replace(".", ","))
            self.no_results.hide()
        else:
            self.results_info.set_text(f"Keine Ergebnisse für „{query}“")
            self.no_results.show()
        dym = self.catalog.index.did_you_mean(query) if n < 3 else None
        if dym:
            uri = "suche:" + GLib.uri_escape_string(dym, None, True)
            self.dym_label.set_markup(f'Meintest du: <a href="{esc(uri)}"><b><i>{esc(dym)}</i></b></a>')
            self.dym_label.show()
        else:
            self.dym_label.hide()

        self.search_stack.set_visible_child_name("results")
        self.show_more()
        self.results_scroller.get_vadjustment().set_value(0)
        self.results_entry.grab_focus_without_selecting()
        self.results_entry.set_position(-1)

    def show_more(self):
        chunk = self.results[self.shown:self.shown + PAGE_SIZE]
        for item in chunk:
            row = ResultRow(self, item, self.current_query)
            self.result_rows[row.key] = row
            self.results_list.add(row)
            row.show_all()
            row.update_state()
        self.shown += len(chunk)
        self.more_btn.set_visible(self.shown < len(self.results))

    def state_for(self, item):
        key = core.norm_filename(item.file_name)
        if key in self.transfers:
            return "laeuft"
        if not self.device:
            return "kein_stift"
        inst = self.inst_by_file.get(key) or self.inst_by_catalog.get(id(item))
        if inst:
            return "update" if inst.update_available else "installiert"
        return "neu"

    def update_result_states(self):
        for row in self.result_rows.values():
            row.update_state()

    def clear_history(self):
        core.clear_history()
        self.history = []
        self.toast("Suchverlauf gelöscht.")

    def clear_cache(self):
        freed = core.clear_download_cache()
        self.toast(f"Zwischenspeicher geleert ({core.format_size(freed)} freigegeben).")

    # --------------------------------------------------------------- Geräte
    def schedule_device_refresh(self, *_):
        if self._dev_timer:
            GLib.source_remove(self._dev_timer)
        self._dev_timer = GLib.timeout_add(450, self.refresh_devices)

    def refresh_devices(self, *_):
        self._dev_timer = 0
        try:
            devices = core.find_devices()
        except Exception:  # noqa: BLE001
            devices = []
        if self.manual_device:
            if os.path.isdir(self.manual_device.mount_path):
                if all(d.key != self.manual_device.key for d in devices):
                    devices.append(self.manual_device)
            else:
                self.manual_device = None
        old_key = self.device.key if self.device else None
        self.devices = devices
        self.device = next((d for d in devices if d.key == old_key), devices[0] if devices else None)

        self.dev_combo.handler_block(self._combo_handler)
        self.dev_combo.remove_all()
        for d in devices:
            self.dev_combo.append(d.key, f"{d.display_name} – {d.label}")
        if self.device:
            self.dev_combo.set_active_id(self.device.key)
        self.dev_combo.handler_unblock(self._combo_handler)
        self.dev_combo.set_visible(len(devices) > 1)

        if old_key and not self.device:
            if time.monotonic() - self._just_ejected > 8:
                self.toast("Der tiptoi-Stift wurde getrennt.")
        elif self.device and self.device.key != old_key:
            self.toast(f"{self.device.display_name} erkannt.")
        self.update_device_bar()
        self.refresh_installed()
        return False

    def _on_combo_changed(self, combo):
        key = combo.get_active_id()
        self.device = next((d for d in self.devices if d.key == key), self.device)
        self.update_device_bar()
        self.refresh_installed()

    def update_device_bar(self):
        d = self.device
        if not d:
            self.dev_icon.set_from_gicon(Gio.ThemedIcon.new_from_names(
                ["drive-removable-media-symbolic", "drive-removable-media"]), Gtk.IconSize.DIALOG)
            self.dev_icon.get_style_context().add_class("dim")
            self.dev_name.set_text("Kein tiptoi-Stift verbunden")
            self.dev_details.set_text("Stift einschalten und mit dem USB-Kabel an den Computer anschließen.")
            self.storage_box.hide()
            self.eject_btn.hide()
            self.update_result_states()
            return
        self.dev_icon.get_style_context().remove_class("dim")
        gicon = None
        if d.gio_mount is not None:
            try:
                gicon = d.gio_mount.get_icon()
            except Exception:  # noqa: BLE001
                gicon = None
        if gicon is None:
            gicon = Gio.ThemedIcon.new_from_names(["drive-removable-media-usb", "drive-removable-media",
                                                   "media-removable"])
        self.dev_icon.set_from_gicon(gicon, Gtk.IconSize.DIALOG)
        name = d.display_name
        if d.label and d.label.lower() != "tiptoi":
            name += f" „{d.label}“"
        self.dev_name.set_text(name)
        details = [d.mount_path]
        if d.usb and d.usb.serial:
            details.append(f"Seriennummer {d.usb.serial}")
        if d.manual:
            details.append("manuell gewählt")
        self.dev_details.set_text("  ·  ".join(details))
        try:
            total, used, free = d.usage()
            self.level.set_value(used / total if total else 0)
            self.storage_label.set_markup(f"<b>{esc(core.format_size(free))}</b> frei von "
                                          f"{esc(core.format_size(total))}")
            self.storage_box.show()
        except OSError:
            self.storage_box.hide()
        self.eject_btn.show()
        self.eject_btn.set_sensitive(not self.transfers and not self._ejecting)
        self.eject_btn.set_tooltip_text("Erst alle Übertragungen abschließen" if self.transfers
                                        else "Stift sicher auswerfen")
        self.update_result_states()

    def choose_folder(self):
        dlg = Gtk.FileChooserNative.new("Ordner des tiptoi-Stifts wählen", self,
                                        Gtk.FileChooserAction.SELECT_FOLDER, "Auswählen", "Abbrechen")
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            path = dlg.get_filename()
            if path:
                self.manual_device = core.device_from_folder(path)
                self.device = self.manual_device
                self.refresh_devices()
        dlg.destroy()

    # ------------------------------------------------------------ Auswerfen
    def on_eject(self, *_):
        d = self.device
        if not d:
            return
        if self.transfers:
            self.toast("Bitte warte, bis alle Übertragungen fertig sind.")
            return
        self._ejecting = True
        set_button(self.eject_btn, "Wird ausgeworfen …", "content-loading-symbolic", sensitive=False)

        def after_sync():
            mount = d.gio_mount
            op = Gtk.MountOperation.new(self)
            if mount is not None and mount.can_eject():
                mount.eject_with_operation(Gio.MountUnmountFlags.NONE, op, None, self._eject_done, ("eject", d))
            elif mount is not None and mount.can_unmount():
                mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op, None, self._eject_done,
                                             ("unmount", d))
            else:
                threading.Thread(target=self._eject_udisks, args=(d,), daemon=True).start()
            return False

        def sync():
            os.sync()  # alle Schreibpuffer leeren
            GLib.idle_add(after_sync)
        threading.Thread(target=sync, daemon=True).start()

    def _eject_udisks(self, d):
        try:
            core.eject_with_udisks(d.device_file)
            GLib.idle_add(self._eject_finished, d, None)
        except core.TiptoiError as e:
            GLib.idle_add(self._eject_finished, d, str(e))

    def _eject_done(self, mount, result, data):
        kind, d = data
        try:
            if kind == "eject":
                mount.eject_with_operation_finish(result)
            else:
                mount.unmount_with_operation_finish(result)
            err = None
        except GLib.Error as e:
            err = e.message
        self._eject_finished(d, err)

    def _eject_finished(self, d, err):
        self._ejecting = False
        set_button(self.eject_btn, "Auswerfen", "media-eject-symbolic", sensitive=True)
        if err:
            self.error_dialog("Auswerfen nicht möglich",
                              f"{err}\n\nSchließe Programme, die gerade auf den Stift zugreifen "
                              "(z. B. ein Dateimanager-Fenster), und versuche es erneut.")
        else:
            if d is self.manual_device:
                self.manual_device = None
            self._just_ejected = time.monotonic()
            self.toast("Der Stift kann jetzt sicher abgezogen werden. 👋")
        self.refresh_devices()
        return False

    # ---------------------------------------------------- Installierte Inhalte
    def refresh_installed(self):
        d = self.device
        self._inst_gen += 1
        gen = self._inst_gen
        if not d:
            self._installed_done(gen, None, [])
            return
        cat = self.catalog

        def work():
            try:
                items = core.scan_installed(d.mount_path, cat)
            except Exception:  # noqa: BLE001
                items = []
            GLib.idle_add(self._installed_done, gen, d, items)
        threading.Thread(target=work, daemon=True).start()

    def _installed_done(self, gen, d, items):
        if gen != self._inst_gen:
            return False
        self.installed = items
        self.inst_by_file = {core.norm_filename(i.file_name): i for i in items}
        self.inst_by_catalog = {id(i.catalog): i for i in items if i.catalog is not None}
        self.render_installed()
        self.update_device_bar()
        return False

    def render_installed(self):
        for ch in self.inst_list.get_children():
            self.inst_list.remove(ch)
            ch.destroy()
        self.installed_rows = {}
        n = len(self.installed)
        title = f"Auf dem Stift ({n})" if self.device else "Auf dem Stift"
        self.main_stack.child_set_property(self.installed_page, "title", title)
        updates = [i for i in self.installed if i.update_available]
        self.update_all_btn.set_visible(bool(updates))
        if updates:
            self.update_all_btn.set_label(f"Alle aktualisieren ({len(updates)})")
        if not self.device:
            self.inst_summary.set_text("")
            self.inst_stack.set_visible_child_name("nodevice")
            return
        if not n:
            self.inst_summary.set_text("Keine Inhalte")
            self.inst_stack.set_visible_child_name("empty")
            return
        total = sum(i.size for i in self.installed)
        self.inst_summary.set_text(f"{n} {'Inhalt' if n == 1 else 'Inhalte'} · {core.format_size(total)} belegt")
        for inst in self.installed:
            row = InstalledRow(self, inst)
            self.installed_rows[row.key] = row
            self.inst_list.add(row)
            row.show_all()
            row.update_state()
        self.inst_stack.set_visible_child_name("list")

    def _inst_filter_func(self, row):
        q = core.skey(self.inst_filter.get_text())
        if not q:
            return True
        hay = core.skey(f"{row.inst.title} {row.inst.file_name} {row.inst.kind}")
        return all(t in hay for t in q.split())

    def confirm_uninstall(self, inst):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=f"„{inst.title}“ vom Stift löschen?")
        if inst.kind == "Buch/Spiel":
            extra = ("Das Buch bzw. Spiel funktioniert danach erst wieder, wenn du die Datei erneut "
                     "überträgst. Das geht jederzeit über die Suche." if inst.catalog else
                     "Diese Datei ist nicht im Katalog. Wenn du keine Sicherung hast, ist sie danach weg.")
        else:
            extra = ("Hörbücher und Lieder sind an deinen Stift lizenziert. Zum Wiederherstellen musst du "
                     "sie erneut über dein Ravensburger-Konto herunterladen.")
        d.format_secondary_text(f"{inst.file_name} · {core.format_size(inst.size)}\n\n{extra}")
        d.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        b = d.add_button("Deinstallieren", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("destructive-action")
        d.set_default_response(Gtk.ResponseType.CANCEL)
        resp = d.run()
        d.destroy()
        if resp != Gtk.ResponseType.ACCEPT:
            return

        def work():
            try:
                core.uninstall(inst)
                GLib.idle_add(self._uninstalled, inst, None)
            except core.TiptoiError as e:
                GLib.idle_add(self._uninstalled, inst, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _uninstalled(self, inst, err):
        if err:
            self.error_dialog("Löschen fehlgeschlagen", err)
        else:
            self.toast(f"„{inst.title}“ wurde vom Stift entfernt.")
        self.refresh_installed()
        return False

    # ------------------------------------------------------------ Übertragen
    def install(self, item):
        if item is None:
            return
        if not self.device:
            self.toast("Bitte zuerst den tiptoi-Stift anschließen.")
            return
        key = core.norm_filename(item.file_name)
        if key in self.transfers:
            return
        was_installed = self.state_for(item) in ("update", "installiert")
        self.transfers[key] = {"item": item, "frac": 0.0, "text": "Wartet …", "update": was_installed}
        self._refresh_rows(key)
        self.update_device_bar()
        self.transfer_pool.submit(self._transfer_job, item, self.device, key)

    def update_all(self):
        for inst in list(self.installed):
            if inst.update_available:
                self.install(inst.catalog)

    def _post_progress(self, key, frac, text, force=False):
        now = time.monotonic()
        if not force and now - self._last_post.get(key, 0) < 0.1:
            return
        self._last_post[key] = now
        GLib.idle_add(self._apply_progress, key, frac, text)

    def _apply_progress(self, key, frac, text):
        t = self.transfers.get(key)
        if t is None:
            return False
        t["frac"], t["text"] = frac, text
        for rows in (self.result_rows, self.installed_rows):
            row = rows.get(key)
            if row is not None:
                row.set_progress(frac, text)
        return False

    def _transfer_job(self, item, dev, key):
        try:
            self._post_progress(key, 0.0, "Wird heruntergeladen …", force=True)

            def dl(done, total):
                frac = 0.75 * done / total if total else None
                txt = f"Wird heruntergeladen … {core.format_size(done)}"
                if total:
                    txt += f" von {core.format_size(total)}"
                self._post_progress(key, frac, txt)
            path = core.ensure_downloaded(item, progress=dl)

            def cp(done, total):
                self._post_progress(key, 0.75 + 0.25 * done / total if total else None,
                                    "Wird auf den Stift kopiert …")
            self._post_progress(key, 0.75, "Wird auf den Stift kopiert …", force=True)
            core.copy_to_device(path, dev, item.file_name, progress=cp)
            GLib.idle_add(self._transfer_done, key, item, None)
        except core.TiptoiError as e:
            GLib.idle_add(self._transfer_done, key, item, str(e))
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self._transfer_done, key, item, f"Unerwarteter Fehler: {e}")

    def _transfer_done(self, key, item, err):
        info = self.transfers.pop(key, None) or {}
        self._last_post.pop(key, None)
        self._refresh_rows(key)
        if err:
            self.error_dialog(f"„{item.title}“ konnte nicht übertragen werden", err)
        else:
            if info.get("update"):
                self.toast(f"„{item.title}“ wurde auf die neueste Version aktualisiert.")
            else:
                self.toast(f"„{item.title}“ ist jetzt auf dem Stift. 🎉")
        self.refresh_installed()
        return False

    def _refresh_rows(self, key):
        for rows in (self.result_rows, self.installed_rows):
            row = rows.get(key)
            if row is not None:
                row.update_state()

    # --------------------------------------------------------------- Beenden
    def _on_delete(self, *_):
        if not self.transfers:
            return False
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.NONE, text="Es läuft noch eine Übertragung")
        d.format_secondary_text("Wenn du jetzt beendest, wird der Titel nicht vollständig auf den Stift "
                                "kopiert. Die übrigen Inhalte bleiben unverändert.")
        d.add_button("Weiter warten", Gtk.ResponseType.CANCEL)
        b = d.add_button("Trotzdem beenden", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("destructive-action")
        resp = d.run()
        d.destroy()
        if resp == Gtk.ResponseType.ACCEPT:
            os._exit(0)
        return True


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        icon = os.path.join(HERE, "tiptoi-manager.svg")
        if os.path.exists(icon):
            try:
                Gtk.Window.set_default_icon_from_file(icon)
            except GLib.Error:
                pass
        for name, cb, acc in (("about", self.on_about, None), ("quit", self.on_quit, ["<Control>q"])):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
            if acc:
                self.set_accels_for_action(f"app.{name}", acc)

    def do_activate(self):
        if self.win is None:
            self.win = MainWindow(self)
        self.win.present()

    def on_quit(self, *_):
        if self.win and self.win._on_delete():
            return
        self.quit()

    def on_about(self, *_):
        d = Gtk.AboutDialog(transient_for=self.win, modal=True)
        d.set_program_name(core.APP_NAME)
        d.set_version(core.APP_VERSION)
        d.set_logo_icon_name("tiptoi-manager")
        d.set_comments("Inhalte für den tiptoi-Stift unter Linux suchen, übertragen und verwalten.\n\n"
                       "Inoffizielles Werkzeug – nicht mit der Ravensburger AG verbunden. "
                       "tiptoi® ist eine eingetragene Marke der Ravensburger AG. "
                       "Die Audiodateien werden direkt von den Ravensburger-Servern geladen.")
        d.set_license_type(Gtk.License.MIT_X11)
        d.run()
        d.destroy()


def main():
    GLib.set_prgname("tiptoi-manager")
    GLib.set_application_name(core.APP_NAME)
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
