"""Simple document checks using only free tools (OpenCV + numpy). For SYNTHETIC samples.

These are QUALITY checks, not proof that a document is genuine:
  - file type: extension must be jpg/jpeg/png/pdf AND match the file's real bytes
  - file size: between MIN_BYTES and MAX_BYTES
  - resolution: images must be at least 600 x 400 pixels
  - blur: variance of the Laplacian (low variance = few sharp edges = blurry)
  - darkness: mean brightness too low = photo taken in poor light

Result status:
  PASSED     all checks passed (quality only)
  NEEDS_FIX  at least one check failed -> farmer should retake/re-upload
  REVIEW     accepted but content could not be checked automatically (e.g. PDF)
"""
import os

import cv2
import numpy as np

MAX_BYTES = 2 * 1024 * 1024
MIN_BYTES = 200          # smaller than this = empty or corrupt file
MIN_LONG_SIDE, MIN_SHORT_SIDE = 600, 400
BLUR_THRESHOLD = 100.0      # Laplacian variance below this = blurry
DARK_THRESHOLD = 60.0       # mean grey level below this = too dark

MAGIC = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png", b"%PDF": "pdf"}
EXT_KIND = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".pdf": "pdf"}


def _sniff(content):
    for magic, kind in MAGIC.items():
        if content.startswith(magic):
            return kind
    return None


def _check(name, ok, en, hi, value=None):
    return {"name": name, "ok": ok, "en": en, "hi": hi, "value": value}


def check_document(filename, content):
    """Run all checks. Returns {status, checks:[...], kind, size_bytes}."""
    checks = []
    ext = os.path.splitext(filename or "")[1].lower()
    kind = _sniff(content)
    size = len(content)

    type_ok = ext in EXT_KIND and kind == EXT_KIND[ext]
    checks.append(_check("file_type", type_ok,
                         "File type OK" if type_ok else "Only JPG, PNG or PDF files are accepted (and the file must really be that type)",
                         "फ़ाइल प्रकार ठीक है" if type_ok else "सिर्फ़ JPG, PNG या PDF फ़ाइल चलेगी", value=kind or ext))
    size_ok = MIN_BYTES <= size <= MAX_BYTES
    checks.append(_check("file_size", size_ok,
                         f"Size OK ({size // 1024} KB)" if size_ok else f"File must be between 200 bytes and 2 MB (this is {size} bytes)",
                         "आकार ठीक है" if size_ok else "फ़ाइल खाली है या 2 MB से बड़ी है", value=size))
    if not (type_ok and size_ok):
        return {"status": "NEEDS_FIX", "checks": checks, "kind": kind, "size_bytes": size}

    if kind == "pdf":
        checks.append(_check("content", True, "PDF accepted; content needs a manual review",
                             "PDF मिल गई; इसकी जाँच अधिकारी करेंगे"))
        return {"status": "REVIEW", "checks": checks, "kind": kind, "size_bytes": size}

    img = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        checks.append(_check("readable", False, "Image could not be opened", "फ़ोटो खुल नहीं पाई"))
        return {"status": "NEEDS_FIX", "checks": checks, "kind": kind, "size_bytes": size}

    h, w = img.shape
    res_ok = max(h, w) >= MIN_LONG_SIDE and min(h, w) >= MIN_SHORT_SIDE
    checks.append(_check("resolution", res_ok,
                         f"Resolution OK ({w}x{h})" if res_ok else f"Photo too small ({w}x{h}); need at least 600x400",
                         "फ़ोटो का साइज़ ठीक है" if res_ok else "फ़ोटो बहुत छोटी है, पास से साफ़ फ़ोटो लें", value=[w, h]))
    sharpness = float(cv2.Laplacian(img, cv2.CV_64F).var())
    sharp_ok = sharpness >= BLUR_THRESHOLD
    checks.append(_check("blur", sharp_ok,
                         "Photo is sharp" if sharp_ok else "Photo is blurry; text cannot be read. Hold the phone steady and retake",
                         "फ़ोटो साफ़ है" if sharp_ok else "फ़ोटो धुंधली है, लिखावट नहीं पढ़ी जा रही। फ़ोन स्थिर रखकर दोबारा लें",
                         value=round(sharpness, 1)))
    brightness = float(img.mean())
    light_ok = brightness >= DARK_THRESHOLD
    checks.append(_check("lighting", light_ok,
                         "Lighting OK" if light_ok else "Photo is too dark. Retake in good light",
                         "रोशनी ठीक है" if light_ok else "फ़ोटो बहुत अंधेरी है, अच्छी रोशनी में दोबारा लें",
                         value=round(brightness, 1)))
    status = "PASSED" if all(c["ok"] for c in checks) else "NEEDS_FIX"
    return {"status": status, "checks": checks, "kind": kind, "size_bytes": size}
