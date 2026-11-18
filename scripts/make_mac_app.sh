#!/bin/zsh
# Builds Upnext.app in ~/Applications. It's a thin wrapper that starts this
# folder's Python environment, so pulling new code updates the app too.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Upnext.app"

"$ROOT/scripts/setup.sh"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/Upnext" <<EOF
#!/bin/zsh
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m upnext >> "\$HOME/Library/Logs/Upnext.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/Upnext"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Upnext</string>
  <key>CFBundleDisplayName</key><string>Upnext</string>
  <key>CFBundleIdentifier</key><string>com.rahulchandra.upnext</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleExecutable</key><string>Upnext</string>
  <key>CFBundleIconFile</key><string>Upnext</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppleEventsUsageDescription</key><string>Upnext reads what VLC is playing so it can get the next episode ready.</string>
</dict></plist>
EOF

if [ -f "$ROOT/assets/Upnext.icns" ]; then
  cp "$ROOT/assets/Upnext.icns" "$APP/Contents/Resources/Upnext.icns"
fi
touch "$APP"
echo "Built $APP. Open it from Finder, Spotlight or Launchpad, and drag it to the Dock to keep it there."
