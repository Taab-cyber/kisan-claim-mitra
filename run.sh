#!/usr/bin/env sh
# Local run (Linux/macOS, or Git Bash on Windows):
#   ./run.sh           -> install, train NLU if needed, start on http://localhost:8000
#   ./run.sh test      -> also run pytest and run_tests.py (writes TEST_EVIDENCE.md)
set -e
cd "$(dirname "$0")"

# 1) virtual environment (Python 3.11)
if [ ! -d .venv ]; then
  if command -v py >/dev/null 2>&1; then py -3.11 -m venv .venv; else python3.11 -m venv .venv; fi
fi
if [ -f .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi

# 2) dependencies
"$PY" -m pip install -q -r requirements.txt

# 3) train our NLU model (only if missing)
if [ ! -f agent/nlu/model.joblib ]; then
  "$PY" -m agent.nlu.gen_data
  "$PY" -m agent.nlu.train
fi

# 4) optional tests
if [ "$1" = "test" ]; then
  "$PY" -m pytest -q
  PYTHONIOENCODING=utf-8 "$PY" run_tests.py
fi

# 5) start (mock portal is mounted at /portal, judge console at /console.html)
PORT="${PORT:-8000}"
echo "Open http://localhost:$PORT"
PORT="$PORT" "$PY" -m uvicorn server:app --host 0.0.0.0 --port "$PORT"
