#!/usr/bin/env bash
# build.sh
#
# Builds OOT SW2SE for Linux: a single executable file, linux/dist/oot-sw2se.pyz,
# that holds oot_sw2se.py together with the upstream ../editor.html (bundled
# unchanged), the icon and the license. Linux counterpart of ../build.ps1 and
# ../macos/build.sh. It needs only Python 3.8 or later, which also runs it.
#
# Usage: linux/build.sh [--appimage]
#   --appimage  also builds linux/dist/OOT_SW2SE-<version>-<arch>.AppImage
#               with appimagetool (from PATH, or set APPIMAGETOOL=/path/to/it).
#               The AppImage starts the same .pyz with the system's python3.
#
# Files are assembled in .build first and only replace those in dist once
# every step has succeeded, so a failed build keeps the last good one.

# Linux version by aut0mat3d/Claude, 2026: vibe-coded with Claude (Anthropic).
# Released under the MIT License, like the rest of OOT SW2SE (see ../LICENSE).

set -euo pipefail

# Resolve paths from this script's location, not the caller's directory.
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
build="$here/.build"
dist="$here/dist"

appimage=0
for arg in "$@"; do
  case "$arg" in
    --appimage) appimage=1 ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown option $arg (see --help)" >&2; exit 2 ;;
  esac
done

if ! command -v python3 >/dev/null; then
  echo "error: python3 is required" >&2
  exit 1
fi

# Take the version from AssemblyVersion("x.y.z.w") in ../Program.cs, the
# upstream source of truth, keeping the first three parts like the Windows
# and macOS builds do.
version="$(sed -n 's/.*AssemblyVersion("\([0-9]*\.[0-9]*\.[0-9]*\).*/\1/p' "$repo/Program.cs" | head -n 1)"
if [[ -z "$version" ]]; then
  echo "error: no AssemblyVersion found in $repo/Program.cs" >&2
  exit 1
fi
for file in editor.html editor.ico LICENSE; do
  if [[ ! -f "$repo/$file" ]]; then
    echo "error: $repo/$file not found" >&2
    exit 1
  fi
done

rm -rf "$build"
mkdir -p "$build/app"

# The zipapp: the host module, a __main__ that starts it, and its resources.
cp "$here/oot_sw2se.py" "$build/app/"
cp "$repo/editor.html" "$repo/editor.ico" "$build/app/"
cp "$repo/LICENSE" "$build/app/LICENSE.txt"
printf '%s\n' "$version" > "$build/app/VERSION"
cat > "$build/app/__main__.py" <<'PY'
import sys
import oot_sw2se
sys.exit(oot_sw2se.main())
PY
python3 -I -m zipapp "$build/app" --compress --python "/usr/bin/env python3" --output "$build/oot-sw2se.pyz"
chmod 755 "$build/oot-sw2se.pyz"

# Quick check that the bundle starts and finds its resources, both by
# absolute path and as ./oot-sw2se.pyz (zipimport sees these differently).
# It runs from a folder without editor.html or Program.cs, so it can't fall
# back to repository files.
check_version() {
  local reported
  reported="$(cd "$build" && "$@" --version)"
  if [[ "$reported" != "OOT SW2SE $version" ]]; then
    echo "error: '$* --version' reports '$reported'" >&2
    exit 1
  fi
}
check_version python3 -I "$build/oot-sw2se.pyz"
check_version ./oot-sw2se.pyz
cp "$repo/LICENSE" "$build/LICENSE.txt"

if (( appimage )); then
  tool="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
  if [[ -z "$tool" ]]; then
    echo "error: appimagetool not found; install it or set APPIMAGETOOL=/path/to/appimagetool" >&2
    exit 1
  fi
  arch="$(uname -m)"
  appdir="$build/OOT_SW2SE.AppDir"
  mkdir -p "$appdir/usr/lib/oot-sw2se" "$appdir/usr/share/applications"
  cp "$build/oot-sw2se.pyz" "$appdir/usr/lib/oot-sw2se/"
  cp "$repo/LICENSE" "$appdir/usr/lib/oot-sw2se/LICENSE.txt"

  # The desktop entry and icons come from the same code that --install uses.
  python3 -I - "$here" "$appdir" <<'PY'
import os, shutil, sys
sys.path.insert(0, sys.argv[1])
import oot_sw2se
appdir = sys.argv[2]
icons = oot_sw2se.write_icons(os.path.join(appdir, "usr/share/icons/hicolor"))
shutil.copyfile(icons[256], os.path.join(appdir, "oot-sw2se.png"))
entry = oot_sw2se.desktop_entry("oot-sw2se")
for path in ("oot-sw2se.desktop", "usr/share/applications/oot-sw2se.desktop"):
    with open(os.path.join(appdir, path), "w") as file:
        file.write(entry)
PY
  ln -s oot-sw2se.png "$appdir/.DirIcon"

  cat > "$appdir/AppRun" <<'SH'
#!/bin/sh
# Starts the bundled editor with the system's Python 3.
here="${APPDIR:-$(dirname "$(readlink -f "$0")")}"
if ! command -v python3 >/dev/null 2>&1; then
  message="OOT SW2SE needs Python 3. Install the python3 (or python) package of your distribution."
  zenity --error --text="$message" 2>/dev/null || kdialog --error "$message" 2>/dev/null || echo "$message" >&2
  exit 1
fi
exec python3 -I "$here/usr/lib/oot-sw2se/oot-sw2se.pyz" "$@"
SH
  chmod 755 "$appdir/AppRun"

  ARCH="$arch" "$tool" --no-appstream "$appdir" "$build/OOT_SW2SE-$version-$arch.AppImage" >&2
fi

# Everything succeeded: swap the new files in for the old ones.
mkdir -p "$dist"
rm -f "$dist/oot-sw2se.pyz" "$dist"/OOT_SW2SE-*.AppImage
mv "$build/oot-sw2se.pyz" "$build/LICENSE.txt" "$dist/"
echo "$dist/oot-sw2se.pyz"
if (( appimage )); then
  mv "$build/OOT_SW2SE-$version-$arch.AppImage" "$dist/"
  echo "$dist/OOT_SW2SE-$version-$arch.AppImage"
fi
