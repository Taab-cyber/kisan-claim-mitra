"""Phase 2: trained NLU (intent model) + rule-based entities."""
import pytest

from agent.nlu.entities import extract_app_no, extract_crop, extract_season
from agent.nlu.predict import predict
from agent.nlu.train import train


@pytest.mark.parametrize("text", [
    "KRB-2026-00417",
    "my number is krb 2026 00417",
    "K R B 2 0 2 6 0 0 4 1 7",
    "केआरबी २०२६ ००४१७",
    "zero zero four one seven",
    "double zero four one seven",
    "शून्य शून्य चार एक सात",
    "number shunya shunya char ek saat hai",
    "00417 ka status bata do",
])
def test_app_number_variants(text):
    assert extract_app_no(text) == "KRB-2026-00417"


def test_no_app_number():
    assert extract_app_no("mera claim status batao") is None
    assert extract_app_no("I have 2 acres") is None


@pytest.mark.parametrize("text,season", [
    ("season rabi 2026-27 karo", "Rabi 2026-27"),
    ("it should be rabi", "Rabi 2026-27"),
    ("मेरी फसल रबी की थी", "Rabi 2026-27"),
    ("kharif 2026", "Kharif 2026"),
    ("जायद", "Zaid 2027"),
    ("rabi karo, app KRB-2025-00417", "Rabi 2026-27"),  # app-number year is ignored
])
def test_season(text, season):
    assert extract_season(text)["season"] == season


def test_crop():
    assert extract_crop("मेरा धान") == "Paddy"
    assert extract_crop("gehun ki fasal") == "Wheat"
    assert extract_crop("hello") is None


@pytest.mark.parametrize("text,intent", [
    ("what is my claim status", "check_status"),
    ("मेरे क्लेम का स्टेटस क्या है", "check_status"),
    ("kaunsa document missing hai", "missing_docs"),
    ("season galat hai rabi karo", "correct_season"),
    ("खतौनी अपलोड करनी है", "upload_doc"),
    ("haan kar do", "approve"),
    ("नहीं", "reject"),
    ("phir se bolo", "repeat"),
    ("namaste", "greet"),
    ("mujhe madad chahiye", "book_help"),
])
def test_intents(text, intent):
    r = predict(text)
    assert r["intent"] == intent and not r["needs_clarification"]


def test_bare_app_number_is_status_request():
    r = predict("KRB-2026-00521")
    assert r["entities"]["app_no"] == "KRB-2026-00521" and r["intent"] == "check_status"


def test_low_confidence_asks_for_clarification():
    for text in ["", "what is the weather today", "xyz"]:
        assert predict(text)["needs_clarification"]


def test_training_meets_target():
    metrics = train(verbose=False)
    assert metrics["held_out_accuracy"] >= 0.95
