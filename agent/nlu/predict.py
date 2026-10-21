"""predict(text) -> intent, confidence, entities.

If the model is not confident enough, `needs_clarification` is True and the
agent must ask a clarifying question instead of guessing.
"""
import os

import joblib

from agent.nlu.entities import extract_entities, normalize
from agent.nlu.train import MODEL_PATH, train

CONFIDENCE_THRESHOLD = 0.45
_model = None


def get_model():
    """Load the trained model once (train it first if the file is missing)."""
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            train(verbose=False)
        _model = joblib.load(MODEL_PATH)
    return _model


def predict(text):
    text_norm = normalize(text)
    entities = extract_entities(text or "")
    if not text_norm:
        return {"intent": "unknown", "confidence": 0.0, "entities": entities,
                "needs_clarification": True}

    model = get_model()
    probs = model.predict_proba([text_norm])[0]
    best = probs.argmax()
    intent, confidence = model.classes_[best], float(probs[best])

    # A bare application number ("KRB-2026-00417") is the farmer answering our question.
    if "app_no" in entities and confidence < CONFIDENCE_THRESHOLD:
        intent, confidence = "check_status", max(confidence, CONFIDENCE_THRESHOLD)

    return {
        "intent": intent,
        "confidence": round(confidence, 3),
        "entities": entities,
        "needs_clarification": confidence < CONFIDENCE_THRESHOLD or intent == "unknown",
    }
