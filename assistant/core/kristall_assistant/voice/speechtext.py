# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning written replies into speakable text, and cutting a token stream
into sentences so speech can start after the first one.

German and English.  The synthesiser's phonemiser (espeak-ng) reads plain
cardinal numbers but stumbles over times, decimals, ordinals in dates, money,
units, abbreviations and markdown; we expand those here.
"""
from __future__ import annotations

import re
import unicodedata

# ----------------------------------------------------------------- numbers → words

_DE_ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
            "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
            "achtzehn", "neunzehn"]
_DE_TENS = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]
_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _de_below_1000(n: int, final: bool = True) -> str:
    h, r = divmod(n, 100)
    out = (("ein" if h == 1 else _DE_ONES[h]) + "hundert") if h else ""
    if r == 0:
        return out
    if r < 20:
        w = _DE_ONES[r]
        if r == 1 and not final:
            w = "ein"
        return out + w
    t, o = divmod(r, 10)
    if o == 0:
        return out + _DE_TENS[t]
    return out + ("ein" if o == 1 else _DE_ONES[o]) + "und" + _DE_TENS[t]


def de_number(n: int) -> str:
    if n < 0:
        return "minus " + de_number(-n)
    if n == 0:
        return "null"
    parts = []
    for size, sg, pl in ((10**9, "eine Milliarde", "Milliarden"), (10**6, "eine Million", "Millionen")):
        q, n = divmod(n, size)
        if q:
            parts.append(sg if q == 1 else f"{_de_below_1000(q, False)} {pl}")
    q, n = divmod(n, 1000)
    tail = ""
    if q:
        tail = ("" if q == 1 else _de_below_1000(q, False)) + "tausend"
    if n:
        tail += _de_below_1000(n, True)
    if tail:
        parts.append(tail)
    return " ".join(parts)


def de_year(n: int) -> str:
    if 1100 <= n <= 1999:
        h, r = divmod(n, 100)
        return _de_below_1000(h) + "hundert" + (_de_below_1000(r) if r else "")
    return de_number(n)


def de_ordinal(n: int, suffix: str = "ten") -> str:
    special = {1: "ers", 3: "drit", 7: "sieb", 8: "ach"}
    if n in special:
        return special[n] + suffix
    base = de_number(n)
    if n < 20:
        return base + suffix
    return base + ("s" + suffix)


def _en_below_1000(n: int) -> str:
    h, r = divmod(n, 100)
    out = []
    if h:
        out.append(_EN_ONES[h] + " hundred")
    if r:
        if r < 20:
            out.append(_EN_ONES[r])
        else:
            t, o = divmod(r, 10)
            out.append(_EN_TENS[t] + ("-" + _EN_ONES[o] if o else ""))
    return " ".join(out)


def en_number(n: int) -> str:
    if n < 0:
        return "minus " + en_number(-n)
    if n == 0:
        return "zero"
    out = []
    for size, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        q, n = divmod(n, size)
        if q:
            out.append(_en_below_1000(q) + " " + name)
    if n:
        out.append(_en_below_1000(n))
    return " ".join(out)


def en_year(n: int) -> str:
    if 1100 <= n <= 1999 or 2010 <= n <= 2099:
        h, r = divmod(n, 100)
        if r == 0:
            return _en_below_1000(h) + " hundred"
        return _en_below_1000(h) + " " + (("oh " + _EN_ONES[r]) if r < 10 else _en_below_1000(r))
    return en_number(n)


_EN_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
           "nine": "ninth", "twelve": "twelfth"}


def en_ordinal(n: int) -> str:
    w = en_number(n)
    head, sep, last = w.rpartition(" ") if " " in w else ("", "", w)
    hyph_head, hs, last2 = last.rpartition("-")
    tgt = last2
    if tgt in _EN_ORD:
        o = _EN_ORD[tgt]
    elif tgt.endswith("y"):
        o = tgt[:-1] + "ieth"
    else:
        o = tgt + "th"
    last = hyph_head + hs + o
    return (head + sep + last) if head else last


# ----------------------------------------------------------------- normalisation

_MONTHS_DE = ("Januar|Jänner|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember")
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️‍]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

_ABBR = {
    "de": [(r"\bz\.\s?B\.", "zum Beispiel"), (r"\bu\.\s?a\.", "unter anderem"), (r"\busw\.", "und so weiter"),
           (r"\bbzw\.", "beziehungsweise"), (r"\bca\.", "circa"), (r"\bd\.\s?h\.", "das heißt"),
           (r"\bNr\.", "Nummer"), (r"\bStr\.", "Straße"), (r"\bDr\.", "Doktor"), (r"\binkl\.", "inklusive"),
           (r"\bggf\.", "gegebenenfalls"), (r"\bevtl\.", "eventuell"), (r"\bvgl\.", "vergleiche"),
           (r"\bmind\.", "mindestens"), (r"\bmax\.", "maximal"), (r"\bmin\.", "Minuten"),
           (r"\bSek\.", "Sekunden"), (r"\bStd\.", "Stunden"), (r"\bz\.\s?T\.", "zum Teil"),
           (r"\bo\.\s?Ä\.", "oder Ähnliches"), (r"\bu\.\s?U\.", "unter Umständen"), (r"\bMio\.", "Millionen"),
           (r"\bMrd\.", "Milliarden"), (r"\bTsd\.", "tausend"), (r"\bggü\.", "gegenüber")],
    "en": [(r"\be\.\s?g\.", "for example"), (r"\bi\.\s?e\.", "that is"), (r"\betc\.", "et cetera"),
           (r"\bDr\.", "Doctor"), (r"\bMr\.", "Mister"), (r"\bMrs\.", "Missus"), (r"\bMs\.", "Miz"),
           (r"\bvs\.", "versus"), (r"\bapprox\.", "approximately"), (r"\bNo\.", "number")],
}
_UNITS = {
    "de": [("°C", " Grad Celsius"), ("°F", " Grad Fahrenheit"), ("°", " Grad"), ("km/h", " Kilometer pro Stunde"),
           ("%", " Prozent"), ("€", " Euro"), ("$", " Dollar"), ("£", " Pfund"), ("&", " und "),
           ("kWh", " Kilowattstunden")],
    "en": [("°C", " degrees Celsius"), ("°F", " degrees Fahrenheit"), ("°", " degrees"), ("km/h", " kilometers per hour"),
           ("%", " percent"), ("€", " euros"), ("$", " dollars"), ("£", " pounds"), ("&", " and "),
           ("kWh", " kilowatt hours")],
}
_WORD_UNITS = {
    "de": {"km": "Kilometer", "kg": "Kilogramm", "g": "Gramm", "m": "Meter", "cm": "Zentimeter", "mm": "Millimeter",
           "GB": "Gigabyte", "MB": "Megabyte", "KB": "Kilobyte", "TB": "Terabyte", "h": "Stunden", "l": "Liter",
           "ml": "Milliliter", "GHz": "Gigahertz", "W": "Watt", "mAh": "Milliamperestunden"},
    "en": {"km": "kilometers", "kg": "kilograms", "g": "grams", "m": "meters", "cm": "centimeters", "mm": "millimeters",
           "GB": "gigabytes", "MB": "megabytes", "KB": "kilobytes", "TB": "terabytes", "h": "hours", "l": "liters",
           "ml": "milliliters", "GHz": "gigahertz", "W": "watts", "mi": "miles", "lb": "pounds", "lbs": "pounds"},
}


def strip_markup(text: str) -> str:
    t = text
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+•]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*(\d+)[.)]\s+", r"\1: ", t, flags=re.M)
    t = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", t)
    t = re.sub(r"^\s*>\s?", "", t, flags=re.M)
    t = re.sub(r"\|", ", ", t)
    t = _EMOJI_RE.sub("", t)
    return t


def normalize(text: str, lang: str = "de") -> str:
    """Written text → text the synthesiser reads correctly."""
    de = lang != "en"
    t = unicodedata.normalize("NFC", strip_markup(text))
    t = _URL_RE.sub(" einen Link " if de else " a link ", t)
    t = t.replace("„", "\"").replace("“", "\"").replace("”", "\"").replace("‚", "'").replace("‘", "'").replace("’", "'")
    t = re.sub(r"\s[–—]\s", ", ", t)
    for pat, rep in _ABBR["de" if de else "en"]:
        t = re.sub(pat, rep, t)
    num = de_number if de else en_number

    # thousands separators first (1.250 / 1,250)
    if de:
        t = re.sub(r"\b(\d{1,3})(?:\.(\d{3}))+(?![.\d])", lambda m: m[0].replace(".", ""), t)
    else:
        t = re.sub(r"\b(\d{1,3})(?:,(\d{3}))+\b", lambda m: m[0].replace(",", ""), t)
    # units after numbers (keep the number, expand the unit)
    units = _WORD_UNITS["de" if de else "en"]
    t = re.sub(r"\b(\d+(?:[.,]\d+)?)\s?(" + "|".join(sorted(map(re.escape, units), key=len, reverse=True)) + r")\b",
               lambda m: f"{m[1]} {units[m[2]]}", t)
    # money: 249,99 € / 249.99 € / €249.99 / $5
    if de:
        t = re.sub(r"(\d+)[,.](\d{2})\s?€", lambda m: f"{num(int(m[1]))} Euro {num(int(m[2]))}", t)
    else:
        t = re.sub(r"[€$](\d+)\.(\d{2})\b", lambda m: f"{num(int(m[1]))} {'euros' if m[0][0] == '€' else 'dollars'} {num(int(m[2]))}", t)
        t = re.sub(r"[€$](\d+)\b", lambda m: f"{num(int(m[1]))} {'euros' if m[0][0] == '€' else 'dollars'}", t)
    # times
    if de:
        def _t(m):
            h, mi = int(m[1]), int(m[2])
            return f"{de_number(h)} Uhr" + (f" {de_number(mi)}" if mi else "")
        t = re.sub(r"\b(\d{1,2}):(\d{2})\s*Uhr\b", _t, t)
        t = re.sub(r"\b(\d{1,2}):(\d{2})\b", _t, t)
    else:
        def _te(m):
            h, mi, ap = int(m[1]), int(m[2]), (m[3] or "").lower().replace(".", "")
            s = en_number(h) + ("" if mi == 0 else (" oh " + en_number(mi) if mi < 10 else " " + en_number(mi)))
            if mi == 0 and not ap:
                s += " o'clock"
            return s + (f" {' '.join(ap)}" if ap else "")
        t = re.sub(r"\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", _te, t, flags=re.I)
        t = re.sub(r"\b(\d{1,2})\s*(am|pm)\b", lambda m: f"{en_number(int(m[1]))} {' '.join(m[2].lower())}", t, flags=re.I)
    # ordinals
    if de:
        def _ord(m):
            prev = (m[1] or "").strip().lower()
            suffix = "ten" if prev in ("am", "vom", "zum", "dem", "den", "im", "beim", "bis", "ab", "seit") else "te"
            return (m[1] or "") + de_ordinal(int(m[2]), suffix) + " "
        t = re.sub(r"(\b\w+\s)?\b(\d{1,2})\.\s(?=(" + _MONTHS_DE + r"|Jahrhundert|Stock|Klasse|Platz|Mal)\b)", _ord, t)
        def _date(m):
            prev = (m[1] or "").strip().lower()
            suf = "ten" if prev in ("am", "vom", "zum", "bis", "ab", "seit", "dem", "den") else "ter"
            return (m[1] or "") + f"{de_ordinal(int(m[2]), suf)} {de_ordinal(int(m[3]), suf)} {de_year(int(m[4]))}"
        t = re.sub(r"(\b\w+\s)?\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", _date, t)
    else:
        t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: en_ordinal(int(m[1])), t)
    # decimals
    if de:
        t = re.sub(r"\b(\d+),(\d+)\b", lambda m: f"{num(int(m[1]))} Komma {' '.join(de_number(int(c)) for c in m[2])}", t)
    else:
        t = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: f"{num(int(m[1]))} point {' '.join(en_number(int(c)) for c in m[2])}", t)
    for sym, rep in _UNITS["de" if de else "en"]:
        t = t.replace(sym, rep)
    # years and remaining integers
    yr = de_year if de else en_year

    def _int(m):
        n = int(m[0])
        if len(m[0]) == 4 and 1100 <= n <= 2099:
            return yr(n)
        return num(n)
    t = re.sub(r"\b\d{1,12}\b", _int, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t.strip()


# ----------------------------------------------------------------- sentence stream

_ABBR_END = re.compile(r"(\b(z\.\s?B|u\.\s?a|usw|bzw|ca|d\.\s?h|Nr|Str|Dr|inkl|ggf|evtl|vgl|Mr|Mrs|Ms|e\.\s?g|i\.\s?e|etc|vs|St|Prof|Hr|Fr)\.)$", re.I)
_MONTH_START = re.compile(r"^\s*(" + _MONTHS_DE + r"|Jahrhundert|Stock|Klasse|Platz|Mal)\b")


class SentenceChunker:
    """Feed streamed text; get back complete sentences as soon as they end."""

    def __init__(self, max_len: int = 220):
        self.buf = ""
        self.max_len = max_len

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            s, self.buf = self.buf[:cut].strip(), self.buf[cut:]
            if s:
                out.append(s)
        return out

    def flush(self) -> list[str]:
        s, self.buf = self.buf.strip(), ""
        return [s] if s else []

    def _find_cut(self) -> int | None:
        b = self.buf
        for m in re.finditer(r"[.!?…]+[\"'“”»)]*(\s+)|\n+", b):
            end = m.end()
            if "\n" in m.group(0):
                return end
            if end >= len(b):           # need to see what follows
                return None
            head = b[:m.start() + 1]
            nxt = b[end:]
            if _ABBR_END.search(head.strip()) or re.search(r"(^|\s)[A-Za-zÄÖÜäöü]\.$", head):
                continue
            pm = re.search(r"(\d+)\.$", head)
            if pm and head.endswith(".") and int(pm.group(1)) <= 31 and _MONTH_START.match(nxt):
                continue
            if re.search(r"\b\d+\.$", head) and nxt[:1].islower():
                continue
            return end
        if len(b) > self.max_len:
            i = max(b.rfind(", ", 0, self.max_len), b.rfind("; ", 0, self.max_len), b.rfind(" – ", 0, self.max_len))
            if i > 40:
                return i + 2
        return None


def detect_language(text: str, default: str = "de") -> str:
    """Tiny stop-word vote between German and English (enough to pick a voice)."""
    words = re.findall(r"[a-zäöüß']+", text.lower())
    if not words:
        return default
    de = {"der", "die", "das", "und", "ist", "ich", "du", "nicht", "ein", "eine", "es", "zu", "mit", "auf",
          "für", "den", "dem", "sich", "auch", "wie", "dir", "dich", "ja", "nein", "habe", "hast", "wird",
          "kann", "gerade", "noch", "schon", "bitte", "gerne", "uhr", "heute", "morgen"}
    en = {"the", "and", "is", "you", "it", "to", "of", "in", "that", "for", "with", "on", "are", "this",
          "be", "have", "your", "i", "can", "will", "what", "it's", "i'm", "there", "today", "tomorrow",
          "sure", "please"}
    sd = sum(w in de for w in words) + 2 * sum(any(c in w for c in "äöüß") for w in words)
    se = sum(w in en for w in words)
    if sd == se:
        return default
    return "de" if sd > se else "en"
