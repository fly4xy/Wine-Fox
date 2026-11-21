#!/bin/bash
# Builds the Windows helpers Wine Fox runs in prefixes (needs mingw-w64):
#   packaging/helpers/build.sh [output dir]      (default: packaging/helpers/bin)
#   elevate.exe            the command line as administrator
#   explorer.exe, explorer32.exe    "open file location" in the Linux file manager (64- and 32-bit)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/bin}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"
cp "$HERE/elevate.manifest" "$WORK/"
printf '1 24 "elevate.manifest"\n' > "$WORK/elevate.rc"
(cd "$WORK" && x86_64-w64-mingw32-windres elevate.rc -O coff -o elevate.res.o)
x86_64-w64-mingw32-gcc -O2 -s -municode -o "$OUT/elevate.exe" "$HERE/elevate.c" "$WORK/elevate.res.o"
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -o "$OUT/explorer.exe" "$HERE/explorer.c"
i686-w64-mingw32-gcc -O2 -s -municode -mwindows -o "$OUT/explorer32.exe" "$HERE/explorer.c"
echo "built $OUT/elevate.exe, explorer.exe, explorer32.exe"
