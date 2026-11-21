#!/bin/bash
# Fonts for Windows programs in a Wine prefix.
#
#   scripts/install-fonts.sh --prefix ~/Games/ue [--corefonts --accept-eula]
#
#   (always)      free fonts of this computer that have the metrics of Microsoft's stand in for
#                 them (FontSubstitutes): Carlito for Calibri, Caladea for Cambria, Selawik for
#                 Segoe UI, Liberation for Arial, Times New Roman and Courier New. Text then takes
#                 the same room as on Windows. Missing ones are named with their packages.
#   --corefonts   Microsoft's "Core fonts for the Web" (Arial, Times New Roman, Courier New,
#                 Verdana, Georgia, Trebuchet MS, Comic Sans MS, Impact, Andale Mono, Webdings),
#                 downloaded on this computer from the corefonts project's original packages
#                 and unpacked into C:\windows\Fonts; Liberation then stands in for nothing
#   --accept-eula you accept Microsoft's EULA of these fonts (it is inside each package)
#
# WINE=<wine of the prefix> picks the Wine build (default: wine from PATH). Wine Fox does not
# carry any of these fonts.
set -euo pipefail

PREFIX="" COREFONTS=0 EULA=0
COREFONTS_URL=https://downloads.sourceforge.net/corefonts
COREFONTS_FILES="andale32 arial32 arialb32 comic32 courie32 georgi32 impact32 times32 trebuc32 verdan32 webdin32"

while [ $# -gt 0 ]; do
    case $1 in
        --prefix) PREFIX=$2; shift ;;
        --corefonts) COREFONTS=1 ;;
        --accept-eula) EULA=1 ;;
        -h|--help) sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo ">>> $*"; }

[ -n "$PREFIX" ] || die "--prefix is needed (see --help)"
[ -f "$PREFIX/system.reg" ] || die "$PREFIX is not a Wine prefix (no system.reg)"
command -v fc-list >/dev/null || die "fc-list is needed (package fontconfig)"
FONTS=$PREFIX/drive_c/windows/Fonts
mkdir -p "$FONTS"

# ---- Microsoft's core fonts, from their original packages
if [ $COREFONTS = 1 ]; then
    [ $EULA = 1 ] || die "the core fonts come with Microsoft's EULA: run again with --accept-eula"
    command -v cabextract >/dev/null || die "cabextract is needed (package cabextract)"
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    for name in $COREFONTS_FILES; do
        say "downloading $name.exe"
        curl -fsSL --retry 3 -o "$work/$name.exe" "$COREFONTS_URL/$name.exe" || die "could not download $name.exe"
        cabextract -q -L -F '*.ttf' -d "$work/fonts" "$work/$name.exe" || die "could not unpack $name.exe"
    done
    cp "$work"/fonts/*.ttf "$FONTS/"
    say "core fonts in C:\\windows\\Fonts: $(ls "$work"/fonts/*.ttf | wc -l) files"
fi

# ---- free stand-ins with the same metrics, when this computer has them
have_font() { fc-list -q ":family=$1"; }
has_core() { ls "$FONTS" 2>/dev/null | grep -qi "^$1$"; }

declare -a lines=() missing=()
add() {   # windows name, free font, package hint, core font file that makes it unneeded
    # Microsoft's own is there: no stand-in (one from an earlier run goes away)
    if [ -n "$4" ] && has_core "$4"; then lines+=("\"$1\"=-"); return; fi
    if have_font "$2"; then lines+=("\"$1\"=\"$2\""); say "$1 -> $2"
    else missing+=("$2 ($3)"); fi
}
add "Calibri" "Carlito" "fonts-crosextra-carlito / ttf-carlito" ""
add "Cambria" "Caladea" "fonts-crosextra-caladea / ttf-caladea" ""
add "Segoe UI" "Selawik" "github.com/microsoft/Selawik" ""
add "Arial" "Liberation Sans" "fonts-liberation / ttf-liberation" "arial.ttf"
add "Times New Roman" "Liberation Serif" "fonts-liberation / ttf-liberation" "times.ttf"
add "Courier New" "Liberation Mono" "fonts-liberation / ttf-liberation" "cour.ttf"

if [ ${#lines[@]} -gt 0 ]; then
    reg=$(mktemp --suffix=.reg)
    {
        printf 'Windows Registry Editor Version 5.00\r\n\r\n'
        printf '[HKEY_LOCAL_MACHINE\\Software\\Microsoft\\Windows NT\\CurrentVersion\\FontSubstitutes]\r\n'
        printf '%s\r\n' "${lines[@]}"
    } > "$reg"
    WINEPREFIX=$PREFIX ${WINE:-wine} regedit /S "$reg" 2>/dev/null \
        || die "could not write FontSubstitutes (set WINE to the wine of the prefix)"
    rm -f "$reg"
fi
if [ ${#missing[@]} -gt 0 ]; then
    echo
    echo "Not on this computer, install them for the same text sizes as on Windows:"
    printf '  %s\n' "${missing[@]}"
fi
say "done; programs started from now on see the fonts"
