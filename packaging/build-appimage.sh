#!/bin/bash
# Builds dist/WineFox-<version>-x86_64.AppImage.
#
# A portable Python (python-appimage, manylinux2014) with PySide6 and Wine Fox installed
# into it, so the AppImage does not depend on the system Python or Qt.
# Needs: bash, curl, python3 (to read the GitHub API), binutils (objdump, for the glibc check).
#
# Environment:
#   WORK       build directory (default: ~/.cache/winefox-appimage)
#   PY_SERIES  Python version (default: 3.12)
#   PREFIX_PACK the patch pack for prefixes (default: the newest wine-fx/work/<version>/prefix-pack)
#   UPDATE_BASE where the AppImage and latest.json are downloaded from (default: the site's)
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-$HOME/.cache/winefox-appimage}
PY_SERIES=${PY_SERIES:-3.12}
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/winefox/__init__.py")
OUT=$HERE/dist/WineFox-$VERSION-x86_64.AppImage
mkdir -p "$WORK" "$HERE/dist"

# the download URL of the release asset of repo $1, tag $2, whose name matches regex $3
asset_url()
{
    curl -fsSL "https://api.github.com/repos/$1/releases/tags/$2" | python3 -c '
import json, re, sys
assets = json.load(sys.stdin)["assets"]
print(next(a["browser_download_url"] for a in assets if re.search(sys.argv[1], a["name"])))' "$3"
}

PY_APPIMAGE=$WORK/python$PY_SERIES.AppImage
if [ ! -f "$PY_APPIMAGE" ]; then
    echo ">>> downloading Python $PY_SERIES"
    curl -fsSL -o "$PY_APPIMAGE" "$(asset_url niess/python-appimage "python$PY_SERIES" "cp3${PY_SERIES#3.}-manylinux2014_x86_64\.AppImage$")"
fi
TOOL=$WORK/appimagetool
if [ ! -f "$TOOL" ]; then
    echo ">>> downloading appimagetool"
    curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
fi
chmod +x "$PY_APPIMAGE" "$TOOL"
export APPIMAGE_EXTRACT_AND_RUN=1

echo ">>> preparing AppDir"
APPDIR=$WORK/squashfs-root
rm -rf "$APPDIR"
(cd "$WORK" && "$PY_APPIMAGE" --appimage-extract >/dev/null)
rm -f "$APPDIR"/AppRun "$APPDIR"/*.desktop "$APPDIR"/*.png "$APPDIR"/*.svg "$APPDIR"/.DirIcon
rm -rf "$APPDIR"/usr/share/metainfo "$APPDIR"/usr/share/applications
ln -s "python$PY_SERIES" "$APPDIR/opt/python"
ln -sf "python$PY_SERIES" "$APPDIR/opt/python/bin/python3"     # what AppRun runs
PY="$APPDIR/opt/python/bin/python$PY_SERIES"

echo ">>> installing PySide6 and Wine Fox"
"$PY" -m pip install -q --no-warn-script-location --disable-pip-version-check --root-user-action=ignore "$HERE"
SITE=$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')

# not needed at run time: Qt development tools, headers, binding sources
rm -rf "$SITE"/PySide6/{include,typesystems,glue,scripts,doc} "$SITE"/PySide6/Qt/{translations,metatypes}
find "$SITE/PySide6" -maxdepth 1 -type f -perm -u+x ! -name '*.so*' -delete
find "$SITE/PySide6/Qt/libexec" -type f ! -name 'QtWebEngineProcess' -delete 2>/dev/null || true
rm -rf "$APPDIR/opt/python/bin/pyside6-"* "$SITE"/pip "$SITE"/pip-*

# stable versions of the graphics components, so they work without downloading anything
echo ">>> bundling stable DXVK, VKD3D-Proton, DXVK-NVAPI"
BUNDLE=$WORK/bundle
rm -rf "$BUNDLE"
for c in dxvk vkd3d nvapi; do
    XDG_CONFIG_HOME=$BUNDLE/config XDG_DATA_HOME=$BUNDLE/data XDG_STATE_HOME=$BUNDLE/state \
        "$PY" -I -m winefox download get "$c" 2>&1 | tail -1
done
mkdir -p "$APPDIR/opt"
cp -r "$BUNDLE/data/winefox/components" "$APPDIR/opt/components"
ls "$APPDIR"/opt/components/*

# the patch pack for prefixes (Tools, Patches): the fixed Windows modules of Wine that
# wine-fx/build.sh made (wine-fx/work/<version>/prefix-pack), or PREFIX_PACK=<that folder>
mkdir -p "$APPDIR/opt/patches"
packs=${PREFIX_PACK:-$(ls -d "$HERE"/wine-fx/work/*/prefix-pack 2>/dev/null | sort -V | tail -1)}
if [ -n "$packs" ] && [ -f "$packs/pack.toml" ]; then
    id=$(sed -n 's/^id = "\(.*\)"/\1/p' "$packs/pack.toml" | head -1)
    echo ">>> bundling the patch pack $id ($packs)"
    cp -r "$packs" "$APPDIR/opt/patches/$id"
    sed -i 's/\r$//' "$APPDIR/opt/patches/$id/files/bin/"*
    chmod 755 "$APPDIR/opt/patches/$id/files/bin/"*
else
    echo ">>> no patch pack for prefixes (run wine-fx/build.sh first, or set PREFIX_PACK)"
fi

# scripts Wine Fox runs (fetch-autosdk.sh: the AutoSDK download in Wine & components)
mkdir -p "$APPDIR/opt/scripts"
install -m 755 "$HERE/scripts/fetch-autosdk.sh" "$HERE/scripts/install-fonts.sh" "$APPDIR/opt/scripts/"
sed -i 's/\r$//' "$APPDIR/opt/scripts/"*.sh

# Windows helpers run in prefixes (elevate.exe: the command line as administrator); needs mingw-w64
if command -v x86_64-w64-mingw32-gcc >/dev/null; then
    echo ">>> building the Windows helpers"
    bash "$HERE/packaging/helpers/build.sh" "$APPDIR/opt/helpers"
else
    echo ">>> x86_64-w64-mingw32-gcc not found: no elevate.exe (no administrator command line)"
fi

install -m 755 "$HERE/packaging/AppRun" "$APPDIR/AppRun"
install -m 644 "$HERE/packaging/winefox.desktop" "$APPDIR/winefox.desktop"
mkdir -p "$APPDIR/usr/share/icons/hicolor/512x512/apps"
install -m 644 "$HERE/winefox/gui/qml/icon.png" "$APPDIR/winefox.png"
cp "$APPDIR/winefox.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/winefox.png"
ln -sf winefox.png "$APPDIR/.DirIcon"

echo ">>> glibc needed"
# the bundled components are Windows DLLs, plus an optional Vulkan layer of DXVK-NVAPI
# that Wine Fox itself never loads: they do not count
find "$APPDIR" -path "$APPDIR/opt/components" -prune -o -name '*.so*' -type f -exec objdump -T {} + 2>/dev/null |
    grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1

# the AppImage is run by other users than the one who built it (e.g. built as root)
chmod -R a+rX "$APPDIR"

echo ">>> packing $OUT"
ARCH=x86_64 "$TOOL" --no-appstream "$APPDIR" "$OUT" >"$WORK/appimagetool.log" 2>&1 ||
    { tail -20 "$WORK/appimagetool.log"; exit 1; }
du -h "$OUT"

# what Wine Fox's update check reads (winefox/updates.py): put it on the server next to the
# AppImage, at $UPDATE_BASE/latest.json
UPDATE_BASE=${UPDATE_BASE:-https://downloads.lis-carter.site/wine-fox}
NAME=$(basename "$OUT")
printf '{"version": "%s", "file": "%s", "url": "%s/%s", "size": %s, "sha256": "%s"}\n' \
    "$VERSION" "$NAME" "$UPDATE_BASE" "$NAME" "$(stat -c %s "$OUT")" "$(sha256sum "$OUT" | cut -d' ' -f1)" \
    > "$HERE/dist/latest.json"
echo ">>> $HERE/dist/latest.json: upload it with $NAME"
