---
title: Kisan Claim Mitra
emoji: 🌾
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Kisan Claim Mitra · किसान क्लेम मित्र

A **voice-first crop-insurance claim tracker** for Indian farmers, in Hindi and English. A farmer
speaks (or types) a question. The agent checks a claim on an insurance portal, explains approval
and payment **separately**, names missing documents **exactly**, and fixes a wrong season or
uploads a document. It changes anything only **after the farmer approves**, then **re-reads the
portal to verify** the change.

- **Free only:** no API keys, no LLMs, no paid services, no network calls at runtime.
- **We built the agent's brain ourselves:** a small intent model trained from scratch with
  scikit-learn on synthetic data.
- **Synthetic data only:** no real Aadhaar, PAN or bank data. The target is a **mock portal**
  included in this repo.

---

## 1. Run it

**Windows (PowerShell)**, with Python 3.11 installed:
```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn server:app --port 8000
```
**Linux / macOS / Git Bash:** `./run.sh`. Use `./run.sh test` to run all tests first.

Open **http://localhost:8000** for the farmer app and **http://localhost:8000/console.html** for
the judge console. The NLU model trains itself on first use (about 5 seconds).

**Docker:**
```bash
docker build -t kisan-claim-mitra .
docker run -p 7860:7860 kisan-claim-mitra     # http://localhost:7860
```

**Free deploy (Hugging Face Spaces):** create a new Space and choose **Docker** as the SDK. Push
this repo to it. The header at the top of this README already sets `sdk: docker` and
`app_port: 7860`. The same Dockerfile also works on **Render** (free web service, Docker runtime).
The SQLite data is re-seeded on every start.

**Tests:**
```bash
python -m pytest -q        # 106 tests: rules, NLU, agent safety, scenarios, API, signup/OTP/docs
python run_tests.py        # TC1-TC4 + 9 failure cases -> TEST_EVIDENCE.md
```

---

## 2. Architecture

```
Browser (web/)                         FastAPI server (server.py) - one process
┌───────────────────────┐   /api/*    ┌──────────────────────────────────────────────┐
│ index.html  app.js    │ ──────────> │ agent/planner.py   state machine per session │
│ voice.js  listen()    │             │   ├─ agent/nlu/     OUR trained intent model │
│           speak()     │             │   ├─ agent/rules.py plain-code decisions     │
│ console.html (judges) │             │   ├─ agent/approvals.py approval + idempotent│
└───────────────────────┘             │   ├─ agent/verify.py  re-read after actions  │
                                      │   ├─ agent/evidence.py audit log             │
                                      │   └─ agent/tools.py ──HTTP──┐                │
                                      │                             v                │
                                      │ /portal  mock insurance portal (portal/)     │
                                      │          SQLite, seeded at startup           │
                                      └──────────────────────────────────────────────┘
```

**Planner states:** `COLLECT → FETCH → DECIDE → (PROPOSE → AWAIT_APPROVAL → EXECUTE → VERIFY) → RESPOND`.
Every reply returns its `trace`, so you can see which states ran.

| Part | What it does |
|---|---|
| `portal/` | Mock portal. `GET /claims/{app_no}`, `POST .../season`, `POST .../documents`. Every change raises `record_version`. Supports `expected_version` (refuse stale changes) and `idempotency_key` (a repeated request is applied once). A failed lookup returns 404 `not_found`, which is different from 503 `portal_down`. Modes: `normal`, `down`, `slow`, `slow_writes`, `drop_writes`. `/simulate/credit/{app_no}` marks money as paid. |
| `agent/nlu/` | Our trained intent model, plus rule-based entities (application number, season, crop). |
| `agent/tools.py` | `fetch_claim`, `propose_season_correction`, `propose_document_upload`, `execute_action`, `reverify`, `book_help`. Inputs are validated before any call. |
| `agent/rules.py` | **Code only, no ML.** Missing documents are copied exactly. "Paid" only if `payment_status == "credited"` (and the claim is approved). Missing or contradictory data gives **UNCERTAIN**. A failed fetch is never reported as "not found". |
| `agent/approvals.py` | The **server** enforces approval: no change without the owner session's approval, reject means no change, the proposal **expires** if `record_version` changed, there is one action ID and key per proposal, a double-click returns the first result, and **after a timeout the portal is checked before any retry**. |
| `agent/verify.py` | After every action it re-reads the portal separately and gives **VERIFIED / FAILED / PENDING / UNCERTAIN**. An attempt is never treated as proof. |
| `agent/evidence.py` | Logs the session ID, validated inputs, source URL, `record_version`, `fetched_at`, the decision and reason, proposal, approval, execution, verification, and final reply. Secrets are redacted. |
| `agent/replies.py` | Fixed Hindi and English templates. Statuses and document names always come from portal data. |
| `agent/scenarios.py` | TC1-TC4 + failure cases, defined once and used by pytest, `run_tests.py` and the judge console. |

---

## 3. How the NLU was trained (from scratch)

1. **Data:** `agent/nlu/gen_data.py` makes **2,035 synthetic utterances** for 11 intents
   (`check_status, missing_docs, correct_season, upload_doc, apply_insurance, book_help, approve,
   reject, repeat, greet, unknown`). They come from templates in **English, Hindi (Devanagari)
   and Hinglish**. Slots are filled with application numbers (typed, or spoken digit by digit),
   seasons and crops. Noise is added: filler words (umm, ji, bhai, अरे), typos (dropped, swapped
   or doubled letters) and random capitals. The data is saved in `agent/nlu/data/utterances.csv`.
2. **Model:** `agent/nlu/train.py` uses TF-IDF on **character n-grams (2-5)** with
   **LogisticRegression**. Character n-grams work for all three writing styles and tolerate typos
   and speech-to-text mistakes. No pretrained model or embeddings are used.
3. **Evaluation:**

   | Test set | Accuracy |
   |---|---|
   | Held-out 20% of synthetic data (407 utterances) | **99.5%** (target ≥ 95%) |
   | 30 hand-written utterances with phrasings **not** in the templates (`realistic_eval.csv`) | **96.7%** |

   We report the miss honestly: *"which paper is still pending for my claim"* is predicted as
   `check_status` instead of `missing_docs`. We did not tune the data to fix that one sentence.
4. **Confidence threshold 0.45:** below it, or for `unknown`, the agent **asks a clarifying
   question** instead of guessing.
5. **Entities are rules, not ML, because they must be exact.**
   - **Application numbers:** `KRB-2026-00417`, `krb 2026 00417`, `K R B 2 0 2 6…`,
     Devanagari digits `००४१७`, and spoken digits in English, Hindi or Hinglish ("zero zero
     four", "शून्य शून्य चार", "shunya shunya char", "double zero").
   - **Seasons:** kharif/खरीफ, rabi/रबी, zaid/जायद.
   - **Crops:** a small crop dictionary.

Retrain any time: `python -m agent.nlu.gen_data && python -m agent.nlu.train`.

---

## 4. Voice

The browser uses one small interface (`web/voice.js`): **`Voice.listen(lang)`** and
**`Voice.speak(text, lang)`**.

- **`browser` (default):** the Web Speech API (`hi-IN` / `en-IN`) for listening and speaking.
  No key is needed.
- **`verbx`:** set `VOICE_PROVIDER=verbx` and `VERBX_API_KEY` in a gitignored `.env` (see
  `.env.example`). The key is read **only by the backend** and never sent to the browser; a test
  checks this. **The VerbX adapter is a clearly marked stub** (`TODO(VerbX)` in `agent/voice.py`
  and `web/voice.js`) until its API docs are available. Any VerbX error or a 5-second timeout
  makes the app **fall back to the browser voice automatically** and show a small notice.
- The **text box always works**, even with no voice support. Voice input needs Chrome or Edge
  and microphone permission.
- The voice guide reads replies aloud in the chosen language. "Hear again" replays them and 🔊
  mutes them.

---

## 5. Sign-up, mock OTP login and document checks

Flow: **Create account → OTP login → My documents** (3 steps). There is also *Log in with OTP*,
and *Continue as guest* for a quick demo.

- **Sign-up (`/api/auth/signup`):** name, mobile, village, district, land (acres) and main crop.
  You can speak into any field. A spoken mobile number is read back digit by digit ("…सही है?").
  Missing details are **listed and asked for, never guessed**. The mobile number accepts spoken
  or Devanagari digits and must be a 10-digit Indian number starting with 6-9.
- **Mock OTP (`/api/auth/otp/*`):**
  - **Code:** a random 6-digit code that is **shown in a yellow "Demo SMS (mock)" box**. The
    farmer types it in themselves; the app never fills it and never bypasses OTP.
  - **Limits:** valid for 5 minutes, single use, resend after 30 s, locked after 5 wrong tries,
    and compared in constant time.
  - **Evidence:** the OTP and the login token are **redacted** in the evidence log, and the
    mobile number is masked (`98••••••10`).
- **Document checks (`farmer/doccheck.py`, OpenCV + numpy, free):**

  | Check | Rule |
  |---|---|
  | File type | `.jpg/.jpeg/.png/.pdf` **and** the file's real bytes must match (a PDF renamed `.png` is caught) |
  | Size | 200 bytes - 2 MB |
  | Resolution | at least 600 × 400 px |
  | Blur | variance of the Laplacian below 100 = blurry (clear samples score about 3,300+, the blurry sample 1.4) |
  | Light | mean brightness below 60 = too dark |

  Results: **PASSED** (quality only, not proof the document is genuine), **NEEDS_FIX** (retake),
  **REVIEW** (a PDF: accepted, but its content needs an officer), or **MISSING**.
- **Profile:** flagged documents are **highlighted in red** on *My documents*, and the home screen
  shows the "N documents need attention" banner from the mockup.
- **Synthetic samples (`farmer/samples.py` → `web/samples/`):** generated documents stamped
  "SYNTHETIC SAMPLE - NOT A REAL DOCUMENT". The set includes clear ones plus a blurry, a dark, a
  tiny one, and a PDF, so every check can be demonstrated. Each row has a **🧪 Demo file**
  picker that uploads a sample through the real upload path.
- **Demo farmer:** mobile **9876543210**. Its seeded documents match the mockup: Aadhaar passed,
  PAN under review, land record missing, passbook blurry, insurance passed.
- **Privacy:** uploaded files are **not stored**; only the file name, size and check results are
  kept. We never ask for Aadhaar, PAN or bank numbers.

---

## 6. 3-minute demo script

Start at `/`, choose **हिन्दी**, and press **Start**. Keep `/console.html` open in a second tab.

| Time | Do / say | What to point out |
|---|---|---|
| 0:00 | Intro: "Voice-first claim tracker. Own trained NLU, no LLM, no API keys." | Language screen, bilingual labels |
| 0:20 | **TC1:** tap the mic and say *"मेरे क्लेम का स्टेटस बताओ"*. The agent asks for the number. Say *"KRB-2026-00417"*. | Asks before guessing. Status screen shows **Under review**, Kharif 2026, Paddy, with source and IST fetch time. |
| 0:50 | **TC2:** type *"आवेदन KRB-2026-00521 में कौन सा कागज़ बाकी है"* | Red card shows **Land Record (Khatauni)**, the exact portal string. **Upload it** opens the approval screen ("not done yet"). **Approve** gives a result marked **VERIFIED** with expected and observed values. |
| 1:30 | **TC3:** say *"mera rabi 2026-27 ka claim KRB-2026-00633 ka status batao"* | "You asked Rabi 2026-27 / Portal shows Kharif 2026". Say **"haan kar do"** and it is VERIFIED by a fresh read. (The double-click case is shown in the console as **F5**.) |
| 2:00 | **TC4:** switch to EN and type *"has my money come for KRB-2026-00748"* | **Approved** (green) and **Not credited** (amber) cards: "Approved does not mean paid". In the console, press **Simulate credit** and ask again: now it says paid. |
| 2:25 | **Console:** press **Run all 4 tests**, then **Run failure cases** | 13 real runs. Click **F6** to see the timeout, the portal checked before any retry, and a single write. Click **F7** to see `drop_writes` caught as **FAILED**. Show the live evidence log. |
| (extra) | Welcome → **Log in with OTP** → 9876543210 → type the code from the Demo SMS. Tap the red banner, then upload **Bank passbook - BLURRY** from 🧪 Demo file, then the clear one. | OTP typed by the farmer; blurry photo flagged NEEDS_FIX, then fixed to PASSED |
| 2:50 | Close | Approval is enforced by the server, no duplicate actions, approved is never confused with paid, UNCERTAIN instead of guessing. |

---

## 7. Simplifying choices and assumptions

- The portal and agent run in **one process** (portal mounted at `/portal`). The agent still
  calls it over **HTTP**, like an external system.
- **Claim statuses are codes** (`under_review`, `documents_pending`, `approved`, `rejected`);
  replies translate them. **Document names stay exactly as the portal writes them**, even in
  Hindi replies.
- **Spoken 5-digit numbers** are assumed to be year 2026 (`00417` → `KRB-2026-00417`). A
  season said without a year means Kharif 2026, Rabi 2026-27 or Zaid 2027.
- **Document upload** uses a **synthetic sample file reference**
  (`samples/<doc>_synthetic.pdf`). No real files are stored.
- **Book help** creates a local synthetic ticket (`HELP-1001`, call-back "tomorrow 10:00-12:00").
- **Timeouts:** a response that arrives after the time limit (default 2 s, set by
  `PORTAL_TIMEOUT_SECONDS`) counts as a timeout. The agent then re-reads the portal and retries
  at most once with the **same idempotency key**. If the outcome is still unknown, the proposal
  becomes `PENDING_CONFIRMATION` and cannot be cancelled, because it may already be applied.
- **No web fonts are downloaded** (no runtime network calls). Noto Sans or Nirmala UI are used
  if installed.
- Running tests from the judge console **resets the mock portal** to its seed data.
- **Step order differs from the mockup:** the mockup shows documents before OTP login. We verify
  the mobile number with OTP **first**, so documents are only accepted from a verified account.
- Accounts and document results use their own in-memory SQLite DB, re-seeded at startup.

## 8. Limitations (honest)

- The NLU is a small template-trained model. Unusual phrasings can fail (see the miss above);
  when confidence is low it asks again rather than guessing.
- Voice quality depends on the browser and the device's installed voices. Hindi text-to-speech
  may sound robotic, or be missing on some systems (the text is always shown).
- Sessions, proposals and the evidence log live **in memory**, so they reset when the server
  restarts. `TEST_EVIDENCE.md` is the saved record.
- The server is single-instance. Accounts and logins reset on restart. The claim agent does not
  yet use the farmer's uploaded profile documents (it uploads a synthetic sample reference to
  the portal).
- Document checks are image-quality heuristics (type, size, resolution, blur, light). They do not
  read the text (no OCR) and cannot detect forgery.
- The VerbX voice adapter is a stub until its API docs are provided.

## 9. Repo layout

```
portal/      mock insurance portal (FastAPI, SQLite, seed data, failure modes)
farmer/      accounts (signup, mock OTP, profile), doccheck (OpenCV), samples, routes
agent/       nlu/ (gen_data, train, entities, predict), tools, planner, rules,
             approvals, verify, evidence, replies, scenarios, voice
web/         index.html, app.js, account.js, voice.js, styles.css, console.*, samples/
tests/       pytest: portal, nlu, rules, agent safety, scenarios, api, farmer
server.py    main app       run_tests.py -> TEST_EVIDENCE.md
PLAN.md      plan           Dockerfile, run.sh
```

All claims, names and documents in this project are **synthetic**. Never enter real Aadhaar,
PAN or bank details.
