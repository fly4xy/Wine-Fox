#!/bin/bash
# The MSVC toolchain and the Windows SDK for Unreal Engine in a Wine prefix, without Visual
# Studio and without a Windows PC: downloaded from Microsoft's servers on this computer by
# msvc-wine (https://github.com/mstorsjo/msvc-wine), laid out as an AutoSDK, the same layout
# tools/make-autosdk.ps1 makes on Windows.
#
#   scripts/fetch-autosdk.sh --accept-license [--prefix ~/Games/ue] [--engine "/path/UE_5.8"]
#                            [--dest ~/AutoSDK-download] [--archive] [-- <more vsdownload.py options>]
#
#   --accept-license   you accept the Visual Studio and Windows SDK licenses (vsdownload.py
#                      shows where to read them); nothing is downloaded without it
#   --prefix           put it into this prefix as C:\AutoSDK and set UE_SDKS_ROOT there
#   --engine           says which versions the engine wants (Engine/Config/Windows/Windows_SDK.json)
#   --dest             where the download and the AutoSDK folder go (default ~/AutoSDK-download)
#   --no-download      use what an earlier run left in --dest (the download or the AutoSDK)
#   --archive          also pack AutoSDK-<vs>-<msvc>-<sdk>.tar.gz, as make-autosdk.ps1 does (Wine Fox's AutoSDK recipe takes it)
#   after --            passed on to vsdownload.py, e.g. --msvc-version 14.50 --sdk-version 10.0.22621
#
# Nothing of Microsoft's goes into Wine Fox: the files come from Microsoft to you, under their
# licenses, for your own use. The .NET Framework SDK (needed by the editor's SwarmInterface) is
# not part of this download; the script says what to do about it.
set -euo pipefail

MSVC_WINE=https://github.com/mstorsjo/msvc-wine.git
DEST=$HOME/AutoSDK-download
PREFIX="" ENGINE="" ACCEPT=0 ARCHIVE=0 DOWNLOAD=1
EXTRA=()

while [ $# -gt 0 ]; do
    case $1 in
        --accept-license) ACCEPT=1 ;;
        --prefix) PREFIX=$2; shift ;;
        --engine) ENGINE=$2; shift ;;
        --dest) DEST=$2; shift ;;
        --archive) ARCHIVE=1 ;;
        --no-download) DOWNLOAD=0 ;;
        --) shift; EXTRA=("$@"); break ;;
        -h|--help) sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "error: $*" >&2; exit 1; }
say() { echo ">>> $*"; }

[ $ACCEPT = 1 ] || die "read the licenses and run again with --accept-license (see --help)"
for tool in git python3 msiextract; do
    command -v $tool >/dev/null || die "$tool is needed (msiextract: package msitools)"
done
if [ -n "$PREFIX" ]; then
    [ -f "$PREFIX/system.reg" ] || die "$PREFIX is not a Wine prefix (no system.reg)"
fi

# ---- the versions the engine wants, when it says
if [ -n "$ENGINE" ]; then
    json=$ENGINE/Engine/Config/Windows/Windows_SDK.json
    [ -f "$json" ] || die "no $json"
    sdk=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("MainVersion",""))' "$json")
    msvc=$(python3 -c 'import json,sys
d = json.load(open(sys.argv[1]))
p = d.get("PreferredVisualCppVersions") or []
print(p[0].split("-")[0] if p else "")' "$json")
    say "the engine wants Windows SDK ${sdk:-any} and MSVC ${msvc:-any}"
    if [ ${#EXTRA[@]} = 0 ]; then
        echo "    vsdownload.py takes the latest of both unless told otherwise; to pick, run again with"
        echo "    -- and its version options (python3 msvc-wine/vsdownload.py --help lists them)"
    fi
fi

mkdir -p "$DEST"
cd "$DEST"

# ---- msvc-wine: its downloader only; nothing of it is installed
if [ $DOWNLOAD = 0 ]; then
    [ -d vs/VC ] || [ -f AutoSDK/autosdk-info.txt ] || die "no earlier download in $DEST"
elif [ -d msvc-wine/.git ]; then
    say "updating msvc-wine"
    git -C msvc-wine pull --ff-only
else
    say "getting msvc-wine"
    git clone --depth 1 "$MSVC_WINE" msvc-wine
fi

if [ $DOWNLOAD = 1 ]; then
    say "downloading MSVC and the Windows SDK from Microsoft (about 1.6 GB, 5.5 GB unpacked)"
    rm -rf vs
    python3 msvc-wine/vsdownload.py --accept-license --dest "$DEST/vs" "${EXTRA[@]}"
fi

# ---- the AutoSDK layout (or the one an earlier run made)
if [ -d vs/VC ]; then
    vc=$(ls -d vs/VC/Tools/MSVC/*/ 2>/dev/null | sort -V | tail -n 1)
    kits="vs/Windows Kits/10"
    [ -d "$kits" ] || kits=vs/kits/10                # older msvc-wine
    [ -n "$vc" ] || die "no VC/Tools/MSVC in the download"
    [ -d "$kits/Include" ] || die "no Windows SDK (Windows Kits/10) in the download"
    msvc_version=$(basename "$vc")
    sdk_version=$(ls "$kits/Include" | sort -V | tail -n 1)

    # the toolchain folder carries Visual Studio's name: VS2022 for 14.3x, VS2026 for 14.5x
    case $msvc_version in
        14.3*|14.4*) vs_id=VS2022 ;;
        *) vs_id=VS2026 ;;
    esac

    say "MSVC $msvc_version ($vs_id), Windows SDK $sdk_version"
    rm -rf AutoSDK
    win64=AutoSDK/HostWin64/Win64
    mkdir -p "$win64/$vs_id" "$win64/Windows Kits"
    mv "$vc" "$win64/$vs_id/$msvc_version"
    mv "$kits" "$win64/Windows Kits/10"
    [ -d "vs/DIA SDK" ] && mkdir -p "$win64/DIA SDK" && mv "vs/DIA SDK" "$win64/DIA SDK/$vs_id"
    # what is inside, as make-autosdk.ps1 writes it
    cat > AutoSDK/autosdk-info.txt <<EOF
vs=$vs_id
vs_path=msvc-wine download
msvc=$msvc_version
windows_sdk=$sdk_version
llvm=
engine=$ENGINE
created=$(date +%Y-%m-%dT%H:%M:%S)
EOF
    rm -rf vs
else
    info() { sed -n "s/^$1=//p" AutoSDK/autosdk-info.txt; }
    vs_id=$(info vs) msvc_version=$(info msvc) sdk_version=$(info windows_sdk)
fi
# the compiler's telemetry (vctip.exe) hangs under Wine whatever the opt-out says; msvc-wine
# removes it too, and cl.exe does without it
find AutoSDK -iname vctip.exe -delete
say "AutoSDK ready: $DEST/AutoSDK"
if [ $ARCHIVE = 1 ]; then
    archive=$DEST/AutoSDK-$vs_id-$msvc_version-$sdk_version.tar.gz
    say "packing $archive"
    tar -czf "$archive" AutoSDK
fi

# ---- into the prefix
if [ -n "$PREFIX" ]; then
    target=$PREFIX/drive_c/AutoSDK
    [ -e "$target" ] && { say "replacing the previous C:\\AutoSDK"; rm -rf "$target"; }
    cp -a AutoSDK "$target"
    reg=$(mktemp --suffix=.reg)
    {
        printf 'Windows Registry Editor Version 5.00\r\n\r\n[HKEY_CURRENT_USER\\Environment]\r\n"UE_SDKS_ROOT"="C:\\\\AutoSDK"\r\n'
        # Visual Studio telemetry off: the compiler's vctip.exe hangs or crashes under Wine
        for view in 'Microsoft' 'Wow6432Node\\Microsoft'; do
            for v in 17.0 18.0; do
                printf '\r\n[HKEY_LOCAL_MACHINE\\Software\\%s\\VSCommon\\%s\\SQM]\r\n"OptIn"=dword:00000000\r\n' "$view" "$v"
            done
        done
    } > "$reg"
    WINEPREFIX=$PREFIX ${WINE:-wine} regedit /S "$reg" 2>/dev/null || die "could not write the registry (set WINE to the wine of the prefix)"
    rm -f "$reg"
    say "C:\\AutoSDK, UE_SDKS_ROOT=C:\\AutoSDK and Visual Studio telemetry off are in $PREFIX"
fi

cat <<EOF

The .NET Framework SDK is not in this download. The editor's SwarmInterface needs it
("Could not find NetFxSDK install dir"). Either:
  - pack it on a Windows PC with tools/make-autosdk.ps1 and install that
    archive with Wine Fox's AutoSDK recipe (it registers the SDK), or
  - copy "C:\\Program Files (x86)\\Windows Kits\\NETFXSDK\\4.8" from any Windows PC into
    C:\\AutoSDK\\HostWin64\\Win64\\Windows Kits\\NETFXSDK\\4.8 and register it:
      wine reg add 'HKLM\\SOFTWARE\\Microsoft\\Microsoft SDKs\\NETFXSDK\\4.8' /v KitsInstallationFolder \\
        /d 'C:\\AutoSDK\\HostWin64\\Win64\\Windows Kits\\NETFXSDK\\4.8\\' /f
Unreal Build Tool logs the compiler it uses: look for C:\\AutoSDK in its output.
EOF
