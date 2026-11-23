#!/usr/bin/env bash
# Installiert den tiptoi Manager für den aktuellen Benutzer (kein sudo nötig).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.local/share/tiptoi-manager"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "▶ Prüfe Voraussetzungen …"
if ! python3 -c 'import gi; gi.require_version("Gtk","3.0"); from gi.repository import Gtk' 2>/dev/null; then
    echo "✗ Python-GTK fehlt. Bitte einmalig ausführen:"
    echo "    sudo apt install python3-gi gir1.2-gtk-3.0"
    exit 1
fi
command -v udisksctl >/dev/null || echo "ℹ udisksctl nicht gefunden – Auswerfen klappt trotzdem über GTK/Gio."

echo "▶ Kopiere Programmdateien nach $DEST"
mkdir -p "$DEST" "$BIN" "$APPS" "$ICONS"
install -m 755 "$SRC/tiptoi_manager.py" "$DEST/tiptoi_manager.py"
install -m 644 "$SRC/tiptoi_core.py" "$DEST/tiptoi_core.py"
install -m 644 "$SRC/tiptoi-manager.svg" "$DEST/tiptoi-manager.svg"
install -m 644 "$SRC/tiptoi-manager.svg" "$ICONS/tiptoi-manager.svg"
ln -sf "$DEST/tiptoi_manager.py" "$BIN/tiptoi-manager"

echo "▶ Lege Startmenü-Eintrag an"
sed "s|@EXEC@|python3 $DEST/tiptoi_manager.py|" "$SRC/tiptoi-manager.desktop" > "$APPS/tiptoi-manager.desktop"
chmod 644 "$APPS/tiptoi-manager.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "✓ Fertig! Starte „tiptoi Manager“ über das Startmenü (Kategorie Zubehör/Bildung)"
echo "  oder im Terminal mit:  tiptoi-manager"
