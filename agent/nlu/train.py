"""Train our intent classifier FROM SCRATCH (no pretrained model, no API).

Run:  python -m agent.nlu.train

Model: TF-IDF over character n-grams (works for English, Devanagari and
Hinglish, and is robust to typos) + Logistic Regression.
Reports accuracy on (1) a held-out 20% split of the synthetic data and
(2) a small hand-written set of phrasings that are NOT in the templates.
"""
import csv
import os

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from agent.nlu import gen_data
from agent.nlu.entities import normalize

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data", "utterances.csv")
EVAL_PATH = os.path.join(HERE, "data", "realistic_eval.csv")
MODEL_PATH = os.path.join(HERE, "model.joblib")


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [normalize(r["text"]) for r in rows], [r["intent"] for r in rows]


def build_pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                  sublinear_tf=True, min_df=1)),
        ("clf", LogisticRegression(C=10, max_iter=3000)),
    ])


def train(verbose=True):
    """Generate data if needed, train, evaluate, save. Returns a metrics dict."""
    if not os.path.exists(DATA_PATH):
        gen_data.main()
    texts, labels = load_csv(DATA_PATH)
    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels)

    model = build_pipeline().fit(x_train, y_train)
    held_out_acc = accuracy_score(y_test, model.predict(x_test))
    metrics = {"n_total": len(texts), "n_test": len(x_test), "held_out_accuracy": held_out_acc}
    if verbose:
        print(f"Synthetic utterances: {len(texts)}  (train {len(x_train)} / test {len(x_test)})")
        print(f"Held-out accuracy: {held_out_acc:.3f}")
        print(classification_report(y_test, model.predict(x_test), digits=3))

    if os.path.exists(EVAL_PATH):
        ev_x, ev_y = load_csv(EVAL_PATH)
        ev_pred = model.predict(ev_x)
        metrics["realistic_accuracy"] = accuracy_score(ev_y, ev_pred)
        if verbose:
            print(f"Hand-written (unseen phrasing) accuracy: {metrics['realistic_accuracy']:.3f}"
                  f"  on {len(ev_x)} utterances")
            for text, gold, pred in zip(ev_x, ev_y, ev_pred):
                if gold != pred:
                    print(f"  MISS: {text!r}  expected={gold}  got={pred}")

    # Final model is trained on ALL synthetic data, then saved.
    final = build_pipeline().fit(texts, labels)
    joblib.dump(final, MODEL_PATH)
    if verbose:
        print(f"Saved model to {MODEL_PATH}")
    return metrics


if __name__ == "__main__":
    train()
