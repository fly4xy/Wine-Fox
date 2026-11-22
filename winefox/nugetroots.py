r"""The root certificates NuGet trusts, in a prefix of Unreal Engine.

Wine trusts the host's roots only, and takes a root out of the prefix once the host drops it.
Linux CA lists are made for HTTPS: DigiCert Assured ID Root CA, which signed and timestamped
the NuGet packages of 2019-2021 (Polly 7, OpenTracing...), is no longer in them. UnrealBuildTool's
restore then fails with NU3018 / NU3028 / NU3037. The .NET SDK that comes with the engine has
the lists NuGet itself trusts on Linux (sdk/<version>/trustedroots/*.pem): the roots of them the
prefix lacks go into its Root store. Wine leaves them there (it only takes out roots it
imported from the host).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import struct
from pathlib import Path

from . import registry, wine

log = logging.getLogger(__name__)

_KEY = r"HKEY_LOCAL_MACHINE\Software\Microsoft\SystemCertificates\Root\Certificates"
_PEM = re.compile(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.S)
# in system.reg: [Software\\Microsoft\\SystemCertificates\\Root\\Certificates\\<SHA-1>]
_HAVE = re.compile(r"SystemCertificates\\\\Root\\\\Certificates\\\\([0-9A-Fa-f]{40})\]")
# CERT_ENHKEY_USAGE_PROP_ID: code signing and timestamping only. Wine's chains do not look at it
# (they check the end certificate's usages), Windows tools do.
_USAGE = bytes.fromhex("3014" "06082b06010505070303" "06082b06010505070308")


def _element(prop_id: int, data: bytes) -> bytes:
    """One property of a serialized certificate (Wine's and Windows' WINE_CERT_PROP_HEADER)."""
    return struct.pack("<III", prop_id, 1, len(data)) + data


def blob(der: bytes) -> bytes:
    """The "Blob" value of a certificate in a registry store: its usages, then the certificate."""
    return _element(9, _USAGE) + _element(32, der)


def nuget_roots(engine_root: Path) -> dict[str, bytes]:
    """SHA-1 (upper case hex) -> DER of the roots in the engine's .NET SDK lists."""
    roots = {}
    for pem in sorted(engine_root.glob("Engine/Binaries/ThirdParty/DotNet/*/*/sdk/*/trustedroots/*.pem")):
        for m in _PEM.finditer(pem.read_bytes()):
            der = base64.b64decode(b"".join(m.group(1).split()))
            roots[hashlib.sha1(der).hexdigest().upper()] = der
    return roots


def missing(prefix_path: Path, roots: dict[str, bytes]) -> dict[str, bytes]:
    try:
        have = {h.upper() for h in _HAVE.findall((prefix_path / "system.reg").read_text(errors="replace"))}
    except OSError:
        have = set()
    return {h: der for h, der in roots.items() if h not in have}


def apply(build: wine.WineBuild, env: dict[str, str], prefix_path: Path, engine_root: Path) -> int:
    """Put the engine's NuGet roots the prefix lacks into its Root store; how many went in."""
    add = missing(prefix_path, nuget_roots(engine_root))
    if add:
        lines = []
        for sha1, der in add.items():
            lines += [f"[{_KEY}\\{sha1}]", f'"Blob"=hex:{registry._hex(blob(der))}']
        registry.apply(build, env, lines)
        log.info("%d NuGet root certificates of %s put into %s", len(add), engine_root, prefix_path)
    return len(add)
