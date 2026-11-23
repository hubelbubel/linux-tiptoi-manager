#!/usr/bin/env bash
# Entfernt den tiptoi Manager wieder. Inhalte auf dem Stift bleiben unberührt.
set -eu
rm -rf "$HOME/.local/share/tiptoi-manager"
rm -f "$HOME/.local/bin/tiptoi-manager" \
      "$HOME/.local/share/applications/tiptoi-manager.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/tiptoi-manager.svg"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
echo "✓ tiptoi Manager entfernt."
echo "  Einstellungen/Zwischenspeicher löschen (optional):"
echo "    rm -rf ~/.config/tiptoi-manager ~/.cache/tiptoi-manager"
