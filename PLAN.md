# PLAN — Crop Insurance Claim Tracker (deadline 23 Oct 2026, 11:59 PM IST)

Voice-first agent (Hindi + English) that helps a farmer check a crop-insurance claim,
fix a wrong season, upload a missing document, and book help — on a **mock portal**.
Free only: no API keys, no LLMs, no network calls at runtime. All data synthetic.

## Architecture (one FastAPI process)
```
browser (web/)  --voice/text-->  /api/chat  -->  agent/planner.py (state machine)
                                                   |-- agent/nlu (our trained TF-IDF + LogReg model)
                                                   |-- agent/rules.py (pure code decisions)
                                                   |-- agent/approvals.py (human approval, backend-enforced)
                                                   |-- agent/tools.py --HTTP--> portal/ (mock portal, SQLite)
                                                   |-- agent/verify.py (re-read portal after every action)
                                                   '-- agent/evidence.py (audit log, judge console)
```
Planner states: COLLECT -> FETCH -> DECIDE -> (PROPOSE -> AWAIT_APPROVAL -> EXECUTE -> VERIFY) -> RESPOND.

## Phases (commit after each)
1. **Mock portal** — `portal/`: SQLite seeded at startup with TC1-TC4 (+1 incomplete record).
   GET claim, POST season, POST documents, 404 vs 503, modes `normal|down|slow|drop_writes`,
   `/simulate/credit`, record_version + idempotency keys on writes.
2. **Trained NLU** — `agent/nlu/`: ~2000 synthetic EN/HI/Hinglish utterances with noise;
   char n-gram TF-IDF + LogisticRegression; held-out report (target >= 95%); rule-based entities
   (app no. incl. spoken/Devanagari digits, season, crop); low confidence -> clarifying question.
3. **Agent core** — tools, planner, rules, approvals, idempotency, verify, evidence, replies (HI/EN templates).
4. **Tests** — pytest for every rule, TC1-TC4 and failure cases; `run_tests.py` -> `TEST_EVIDENCE.md`.
5. **Web app** — language choice, home (mic + text + quick buttons), status, approval, judge console.
   Voice behind one interface `listen()` / `speak(text, lang)`:
   - provider `browser` (default, Web Speech API, no key);
   - provider `verbx` via env `VOICE_PROVIDER`, key `VERBX_API_KEY` only in gitignored `.env`,
     used server-side only. **Stub until API docs arrive.** Any VerbX error/timeout -> automatic
     fallback to browser + small notice. Everything must pass with `VOICE_PROVIDER=browser`.
6. **Deploy + docs** — Dockerfile, `run.sh`, README, demo script. Deployed on **Vercel** (free Hobby plan,
   serverless mode) because Hugging Face Docker Spaces are no longer free on our account.
7. **Multi-agent** — the planner became an orchestrator + 7 specialist agents on a message bus
   (same behaviour, all tests unchanged; verifier separated from executor = maker-checker).

Stretch (only after DoD): signup, mock OTP shown in UI, synthetic doc checks (type/size, blur via OpenCV).
Optional later: Supabase as an extra copy of the evidence log only (off by default; SQLite stays the portal DB).

## Test cases
| TC | App no.        | Seed                                          | Expected agent behaviour                    |
|----|----------------|-----------------------------------------------|---------------------------------------------|
| 1  | KRB-2026-00417 | Under review, Kharif 2026, Paddy              | Report status + source + fetched time       |
| 2  | KRB-2026-00521 | missing "Land Record (Khatauni)"              | Name exact doc, propose upload, approve, verify |
| 3  | KRB-2026-00633 | record Kharif 2026, farmer says Rabi 2026-27  | Detect mismatch, propose fix, approve, verify |
| 4  | KRB-2026-00748 | approved, payment not_credited                | "Approved but NOT paid yet" (never "paid")  |

## Simplifying choices (also noted in README)
- Portal and agent run in one process (portal mounted at `/portal`); agent still talks to it over HTTP-style calls.
- Status values are codes (`under_review`, `documents_pending`, `approved`, `rejected`); replies translate them.
- Local dev uses Python 3.11 venv in `.venv/`.
