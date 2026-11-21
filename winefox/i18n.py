"""The interface's language: English (the source texts) or Russian.

Texts are translated by their English source, from winefox/i18n/<language>/*.json (one file
per part of the interface, all merged): {"English": "Перевод"}. A text with a count (%n) has
a list of forms instead: [one, few, many] for Russian (1 файл, 2 файла, 5 файлов), [one,
other] for English, where only such texts are listed.

QML takes them with qsTr("text") and qsTr("%n files", "", count) through Translator; Python
with tr("text") and tr("%n files", n=count). Placeholders %1, %2 stay as they are, for .arg()
in QML and tr(...).replace or format in Python.

Settings.language: "" follows the system, "en", "ru".
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

LANGUAGES = {"en": "English", "ru": "Русский"}
_DIR = Path(__file__).resolve().parent / "i18n"

_current = "en"
_texts: dict[str, str | list[str]] = {}


def system_language() -> str:
    try:
        from PySide6.QtCore import QLocale
        name = QLocale.system().name()
    except ImportError:
        import locale
        name = locale.getlocale()[0] or ""
    return "ru" if name.lower().startswith("ru") else "en"


def _load(language: str) -> dict[str, str | list[str]]:
    texts: dict[str, str | list[str]] = {}
    for file in sorted((_DIR / language).glob("*.json")):
        try:
            texts.update(json.loads(file.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.warning("translations %s: %s", file, e)
    return texts


def set_language(setting: str) -> str:
    """Use the language Settings ask for ("" is the system's); the one now in use."""
    global _current, _texts
    _current = setting if setting in LANGUAGES else system_language()
    _texts = _load(_current)
    return _current


def current() -> str:
    return _current


def _plural(language: str, n: int, forms: list[str]) -> str:
    if language == "ru" and len(forms) >= 3:
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return forms[1]
        return forms[2]
    return forms[0] if n == 1 or len(forms) < 2 else forms[1]


def translate(source: str, n: int = -1) -> str:
    found = _texts.get(source)
    if isinstance(found, list):
        text = _plural(_current, n if n >= 0 else 0, found) if found else source
    else:
        text = found or source
    return text.replace("%n", str(n)) if n >= 0 else text


def tr(source: str, n: int = -1) -> str:
    """The text in the interface's language."""
    return translate(source, n)


def make_translator():
    """A QTranslator that serves qsTr() from the same texts."""
    from PySide6.QtCore import QTranslator

    class Translator(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):
            if not source:
                return ""
            # always the text: Qt takes an empty answer for a translation, not for "none"
            return translate(source, n)

        def isEmpty(self):
            return False

    return Translator()
