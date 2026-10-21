"""Generate SYNTHETIC sample document images for the demo (no real documents, no real numbers).

Run:  python -m farmer.samples      -> writes web/samples/*.png and one .pdf

Some samples are deliberately bad (blurry, dark, tiny) so the document checks
can be demonstrated honestly.
"""
import os

import cv2
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "samples")

# file name -> (title lines, suggested doc type, label, how to spoil it)
SAMPLES = {
    "aadhaar_card_sample.png": (["IDENTITY CARD", "Name: Ramlal Singh (synthetic)", "ID: XXXX XXXX XXXX"], "aadhaar_card", "Aadhaar card - clear", None),
    "land_record_sample.png": (["LAND RECORD (KHATAUNI)", "Khata No: 000 (synthetic)", "Village: Rampur  Area: 3.5 acre"], "land_record", "Land record - clear", None),
    "bank_passbook_sample.png": (["BANK PASSBOOK", "Account holder: Ramlal Singh", "A/c: XXXXXXXX (synthetic)"], "bank_passbook", "Bank passbook - clear", None),
    "bank_passbook_blurry.png": (["BANK PASSBOOK", "Account holder: Ramlal Singh", "A/c: XXXXXXXX (synthetic)"], "bank_passbook", "Bank passbook - BLURRY", "blur"),
    "insurance_papers_sample.png": (["CROP INSURANCE POLICY", "Policy: SYN-0001 (synthetic)", "Season: Kharif 2026  Crop: Paddy"], "insurance_papers", "Insurance papers - clear", None),
    "land_record_dark.png": (["LAND RECORD (KHATAUNI)", "Khata No: 000 (synthetic)", "Village: Rampur"], "land_record", "Land record - TOO DARK", "dark"),
    "aadhaar_card_tiny.png": (["ID CARD", "synthetic"], "aadhaar_card", "Aadhaar card - TOO SMALL", "tiny"),
}
PDF_SAMPLE = ("pan_card_sample.pdf", "pan_card", "PAN card - PDF")


def draw_document(lines, spoil=None):
    """A white 'document' with a border, a title, text lines and a table grid."""
    h, w = 700, 1000
    img = np.full((h, w, 3), 250, np.uint8)
    cv2.rectangle(img, (20, 20), (w - 20, h - 20), (40, 90, 60), 4)
    cv2.putText(img, lines[0], (50, 95), cv2.FONT_HERSHEY_DUPLEX, 1.4, (20, 40, 30), 3)
    for i, line in enumerate(lines[1:]):
        cv2.putText(img, line, (50, 170 + i * 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    for r in range(6):                                   # table rows like a real record
        y = 340 + r * 50
        cv2.line(img, (50, y), (w - 50, y), (90, 90, 90), 2)
    for x in (50, 350, 650, w - 50):
        cv2.line(img, (x, 340), (x, 590), (90, 90, 90), 2)
    cv2.putText(img, "SYNTHETIC SAMPLE - NOT A REAL DOCUMENT", (50, 650),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 180), 2)
    if spoil == "blur":
        img = cv2.GaussianBlur(img, (31, 31), 12)
    elif spoil == "dark":
        img = (img * 0.15).astype(np.uint8)
    elif spoil == "tiny":
        img = cv2.resize(img, (300, 210))
    return img


def minimal_pdf(text):
    """A tiny valid one-page PDF with one line of text (built by hand, no library)."""
    stream = f"BT /F1 18 Tf 50 750 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def sample_list():
    """Metadata for the UI's 'demo file' picker."""
    items = [{"file": f, "doc_type": t, "label": label} for f, (_, t, label, _) in SAMPLES.items()]
    items.append({"file": PDF_SAMPLE[0], "doc_type": PDF_SAMPLE[1], "label": PDF_SAMPLE[2]})
    return items


def ensure_samples():
    """Create the sample files if they are missing (safe to call at every startup)."""
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, (lines, _, _, spoil) in SAMPLES.items():
        path = os.path.join(OUT_DIR, name)
        if not os.path.exists(path):
            cv2.imwrite(path, draw_document(lines, spoil))
    pdf_path = os.path.join(OUT_DIR, PDF_SAMPLE[0])
    if not os.path.exists(pdf_path):
        with open(pdf_path, "wb") as f:
            f.write(minimal_pdf("PAN CARD - SYNTHETIC SAMPLE - NOT A REAL DOCUMENT"))


if __name__ == "__main__":
    ensure_samples()
    print(f"Samples in {OUT_DIR}")
