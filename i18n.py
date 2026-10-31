"""
Interface text lives in strings/<lang>.json, not in the code.
Adding a language = adding one JSON file with the same keys.
"""

import json
import os
from functools import lru_cache

LANGUAGES = {"en": "English", "ar": "العربية"}
RTL_LANGUAGES = {"ar"}  # right-to-left scripts


@lru_cache(maxsize=None)
def _load(lang):
    path = os.path.join(os.path.dirname(__file__), "strings", f"{lang}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def t(key, lang="en", **values):
    """Look up a piece of interface text and fill in any {placeholders}."""
    text = _load(lang).get(key) or _load("en").get(key, key)  # fall back to English
    return text.format(**values) if values else text
