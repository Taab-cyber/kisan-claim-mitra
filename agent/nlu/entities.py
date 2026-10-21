"""Rule-based entity extraction: application number, season, crop.

Rules (not ML) because these values must be exact. Handles:
  - "KRB-2026-00417", "krb 2026 00417", "K R B 2 0 2 6 0 0 4 1 7"
  - Devanagari digits "००४१७" and spoken digits ("zero zero four one seven",
    "शून्य शून्य चार एक सात", "double zero four one seven")
  - seasons kharif/खरीफ, rabi/रबी, zaid/जायद (+ optional year)
  - a small crop dictionary in English / Hindi / Hinglish
"""
import re

DEFAULT_YEAR = 2026          # used when the farmer says only 5 digits or no season year
APP_PREFIX = "KRB"

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Spoken number words -> digit. Hinglish words like "do" (= two, but also "give")
# are AMBIGUOUS and only count when next to other digits.
NUMBER_WORDS = {
    "zero": "0", "oh": "0", "shunya": "0", "sunya": "0", "शून्य": "0", "सुन्य": "0", "जीरो": "0", "ज़ीरो": "0",
    "one": "1", "ek": "1", "एक": "1",
    "two": "2", "do": "2", "दो": "2",
    "three": "3", "teen": "3", "तीन": "3",
    "four": "4", "char": "4", "chaar": "4", "चार": "4",
    "five": "5", "paanch": "5", "panch": "5", "पांच": "5", "पाँच": "5",
    "six": "6", "chhe": "6", "che": "6", "chhah": "6", "छह": "6", "छः": "6", "छे": "6",
    "seven": "7", "saat": "7", "सात": "7",
    "eight": "8", "aath": "8", "आठ": "8",
    "nine": "9", "nau": "9", "नौ": "9",
}
AMBIGUOUS_WORDS = {"do", "char", "che", "oh"}
REPEATERS = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3}

SEASON_WORDS = {
    "kharif": "Kharif", "khareef": "Kharif", "kharib": "Kharif", "खरीफ": "Kharif", "ख़रीफ़": "Kharif",
    "rabi": "Rabi", "rabbi": "Rabi", "रबी": "Rabi",
    "zaid": "Zaid", "zayad": "Zaid", "jayad": "Zaid", "जायद": "Zaid", "ज़ायद": "Zaid",
}

CROPS = {
    "paddy": "Paddy", "rice": "Paddy", "dhan": "Paddy", "dhaan": "Paddy", "धान": "Paddy", "चावल": "Paddy",
    "wheat": "Wheat", "gehu": "Wheat", "gehun": "Wheat", "gehoon": "Wheat", "गेहूं": "Wheat", "गेहूँ": "Wheat",
    "cotton": "Cotton", "kapas": "Cotton", "कपास": "Cotton",
    "sugarcane": "Sugarcane", "ganna": "Sugarcane", "गन्ना": "Sugarcane",
    "maize": "Maize", "corn": "Maize", "makka": "Maize", "मक्का": "Maize",
    "mustard": "Mustard", "sarson": "Mustard", "सरसों": "Mustard",
    "soybean": "Soybean", "soyabean": "Soybean", "सोयाबीन": "Soybean",
    "bajra": "Bajra", "बाजरा": "Bajra", "gram": "Gram", "chana": "Gram", "चना": "Gram",
}

APP_RE = re.compile(r"k\s*-?\s*r\s*-?\s*b\s*[-\s]*(\d{4})\s*[-\s]*(\d{5})", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z]+|[ऀ-ॿ]+|\d+", re.IGNORECASE)


def normalize(text):
    """Lowercase and convert Devanagari digits to ASCII digits."""
    return (text or "").translate(DEVANAGARI_DIGITS).lower().strip()


def _digit_runs(text):
    """Turn the text into runs of consecutive digits, reading spoken number words too."""
    runs, current, pending_repeat = [], [], 1
    for tok in TOKEN_RE.findall(text):
        if tok in REPEATERS:
            pending_repeat = REPEATERS[tok]
            continue
        if tok.isdigit():
            digits, ambiguous = tok, False
        elif tok in NUMBER_WORDS:
            digits, ambiguous = NUMBER_WORDS[tok], tok in AMBIGUOUS_WORDS
        else:
            if current:
                runs.append(current)
            current, pending_repeat = [], 1
            continue
        current.append((digits * pending_repeat, ambiguous))
        pending_repeat = 1
    if current:
        runs.append(current)
    return runs


def _app_from_digits(digits):
    if len(digits) == 9 and digits.startswith("20"):
        return f"{APP_PREFIX}-{digits[:4]}-{digits[4:]}"
    if len(digits) == 5:
        return f"{APP_PREFIX}-{DEFAULT_YEAR}-{digits}"   # assumption noted in README
    return None


def extract_app_no(text):
    """Return a canonical application number like 'KRB-2026-00417', or None."""
    t = normalize(text)
    m = APP_RE.search(t)
    if m:
        return f"{APP_PREFIX}-{m.group(1)}-{m.group(2)}"
    # letters spoken separately: "k r b 2 0 2 6 ..." or "के आर बी"
    t = re.sub(r"\bk\s+r\s+b\b|के\s*आर\s*बी", " ", t)
    for run in _digit_runs(t):
        # try the run as-is, then without ambiguous words at its edges ("... saat do")
        candidates = [run]
        trimmed = list(run)
        while trimmed and trimmed[-1][1]:
            trimmed = trimmed[:-1]
        while trimmed and trimmed[0][1]:
            trimmed = trimmed[1:]
        candidates.append(trimmed)
        for cand in candidates:
            app = _app_from_digits("".join(d for d, _ in cand))
            if app:
                return app
    return None


def extract_season(text):
    """Return {'season': 'Rabi 2026-27', 'year_assumed': bool} or None."""
    t = normalize(text)
    found = None
    for word, name in SEASON_WORDS.items():
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", t):
            found = name
            break
    if not found:
        return None
    t = APP_RE.sub(" ", t)  # the year inside an app number is not the season year
    m = re.search(r"(20\d{2})(?:\s*-\s*(\d{2}))?", t)
    year = int(m.group(1)) if m else DEFAULT_YEAR
    if found == "Rabi":
        season = f"Rabi {year}-{(year + 1) % 100:02d}"   # Rabi spans two years
    elif found == "Zaid" and not m:
        season = f"Zaid {DEFAULT_YEAR + 1}"             # next Zaid after Rabi 2026-27
    else:
        season = f"{found} {year}"
    return {"season": season, "year_assumed": m is None}


def extract_crop(text):
    t = normalize(text)
    for tok in TOKEN_RE.findall(t):
        if tok in CROPS:
            return CROPS[tok]
    return None


def extract_entities(text):
    """All entities found in the text (missing ones are simply left out)."""
    ents = {}
    if app := extract_app_no(text):
        ents["app_no"] = app
    if season := extract_season(text):
        ents["season"] = season["season"]
        ents["season_year_assumed"] = season["year_assumed"]
    if crop := extract_crop(text):
        ents["crop"] = crop
    return ents
