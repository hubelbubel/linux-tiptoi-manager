import os, sys, tempfile, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import fake_gi  # noqa
os.environ["XDG_CACHE_HOME"] = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import tiptoi_core as core, tiptoi_manager as ui
from test_data import CSV, HTML, gme
items = core.parse_catalog_csv(CSV); core.enrich(items, core.parse_metadata_html(HTML))
cat = core.Catalog(items, "6 Titel", core.DEFAULT_CONFIG["image_urls"])
core.load_catalog = lambda cfg=None, force=False: cat
core.fetch_image = lambda item, t, timeout=15: None
pen = tempfile.mkdtemp(prefix="tiptoi_")
gme(os.path.join(pen, "WWW_Bauernhof.gme"), 42, "20180101")
gme(os.path.join(pen, "Eigenes.gme"), 999, "20240101")
core.find_devices = lambda: [core.Device(pen, "tiptoi", "/dev/sdz1", core.UsbInfo("04d6", "e101", "", "", "ABC123"))]
# downloads: write fake gme
def fake_dl(item, progress=None, cancel=None, timeout=60):
    p = os.path.join(tempfile.mkdtemp(), item.file_name); gme(p, int(item.id), item.version)
    if progress: progress(100, 200); progress(200, 200)
    return p
core.ensure_downloaded = fake_dl

app = ui.App(); app.do_startup()
w = ui.MainWindow(app)
time.sleep(0.5)
print("catalog:", w.catalog is cat, "| status:", w.cat_status.get_text())
print("device:", w.device and w.device.display_name, "| name label:", w.dev_name.get_text(), "| details:", w.dev_details.get_text())
print("storage:", w.storage_label.get_text(), "| eject visible:", w.eject_btn.get_visible())
time.sleep(0.3)
print("installed:", [(i.title, i.update_available) for i in w.installed], "| summary:", w.inst_summary.get_text(), "| update-all:", w.update_all_btn.get_visible(), w.update_all_btn.get_label())
# suggestions
w.home_entry.set_text("bau"); w._on_entry_changed(w.home_entry)
print("suggestions:", [r[0] for r in w.home_entry.store.__dict__.get("_rows", [])])
w.run_search("bauernhof")
print("results:", w.results_info.get_text(), [ (k, w.state_for(r.item)) for k, r in w.result_rows.items()])
print("buttons:", [(r.button.get_label(), r.button.get_sensitive()) for r in w.result_rows.values()])
w.run_search("bauernhfo")
print("dym:", w.dym_label.get_text(), w.dym_label.get_visible())
w._on_dym(None, "suche:bauernhof"); print("after dym query:", w.current_query)
w.run_search("xyz"); print("empty:", w.results_info.get_text(), w.no_results.get_visible())
# paging
w.results = items * 10; w.shown = 0; w.show_more(); print("paging shown", w.shown, "more visible", w.more_btn.get_visible())
# install new
w.run_search("englisch")
row = list(w.result_rows.values())[0]
row._on_click()
time.sleep(1.0)
print("after install:", sorted(os.listdir(pen)), "transfers:", w.transfers, "toast:", w.toast_label.get_text())
print("row state now:", w.state_for(row.item), row.button.get_label())
# update via installed page
w.update_all(); time.sleep(1.0)
print("after update:", [(i.file_name, i.version, i.update_available) for i in core.scan_installed(pen, cat)], w.toast_label.get_text())
# uninstall
inst = [i for i in w.installed if i.file_name == "Eigenes.gme"][0]
w.confirm_uninstall(inst); time.sleep(0.5)
print("after uninstall:", sorted(os.listdir(pen)), w.toast_label.get_text())
# filter func
w.inst_filter.set_text("englisch")
print("filter:", [w._inst_filter_func(r) for r in w.installed_rows.values()])
# lucky & go home
w.lucky(); print("lucky:", w.current_query); w.go_home(); print("home:", w.search_stack.get_visible_child_name())
# eject (udisks fallback mocked)
core.eject_with_udisks = lambda dev: None
w.on_eject(); time.sleep(0.5)
print("eject toast:", w.toast_label.get_text())
# device removed
core.find_devices = lambda: []
w.refresh_devices(); time.sleep(0.2)
print("no device:", w.dev_name.get_text(), w.inst_stack.get_visible_child_name(), "| toast:", w.toast_label.get_text())
w.run_search("bauernhof"); print("states no device:", [w.state_for(r.item) for r in w.result_rows.values()])
w.install(items[0]); print("install w/o device toast:", w.toast_label.get_text())
print("delete-event ok:", w._on_delete() is False)
print("SMOKE OK")
