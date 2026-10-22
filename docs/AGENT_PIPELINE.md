# How the agentic pipeline works (walkthrough for reviewers)

Kisan Claim Mitra is a **multi-agent system**. An **orchestrator** coordinates **7 specialist
agents** that talk only through a **message bus**. The agents understand a farmer's request
in Hindi or English, read an insurance portal, propose a fix, wait for the farmer's approval,
make the change exactly once, and have a *different* agent verify it.

> **30-second version:** "The farmer speaks. The intake agent works out what they want using
> a model we trained ourselves. The investigator reads the portal and applies the rules. If
> something needs fixing, the action agent drafts a proposal, but nothing changes until the
> farmer says yes. The server enforces that. The action agent then makes the change exactly
> once, even after timeouts or double clicks. An independent verifier re-reads the portal to
> prove it worked. The responder replies in the farmer's language, and the auditor logs every
> step, so every decision can be explained."

---

## 1. The agents

| Agent | Job | Asked to | Code |
|---|---|---|---|
| **orchestrator** | Keeps each farmer's session memory; runs the state machine; decides who to ask next. Never touches the portal itself. | — (entry point) | [planner.py](../agent/planner.py#L35) |
| **intake** | Understands the farmer: our trained intent model + entity rules | `understand` | [agents.py](../agent/agents.py#L39) |
| **investigator** | Reads the claim from the portal and applies the business rules | `investigate` | [agents.py](../agent/agents.py#L48) |
| **action** | Drafts proposals, records approve/reject, executes approved changes **once** | `propose` `lookup` `decide` `cancel` `execute` `attach_verification` | [agents.py](../agent/agents.py#L68) |
| **verifier** | Re-reads the portal independently and compares it with the intended change | `verify` | [agents.py](../agent/agents.py#L108) |
| **helpdesk** | Books a (synthetic) officer call-back | `book` | [agents.py](../agent/agents.py#L119) |
| **responder** | Writes the Hindi/English reply from fixed templates, using portal data | `compose` | [agents.py](../agent/agents.py#L126) |
| **auditor** | Writes every step into the evidence log, with secrets redacted | `record` | [agents.py](../agent/agents.py#L143) |

**How they talk:** [bus.py](../agent/bus.py#L55). `bus.request(sender, recipient, type, session, **payload)`
creates a `Message`, delivers it to the recipient's `on_<type>` method
([BaseAgent.handle](../agent/agents.py#L28)), and records both the request and the reply.
No agent holds a reference to another agent; [test_multi_agent.py](../tests/test_multi_agent.py)
checks this. An agent asked to do something outside its job refuses: for example, the
verifier cannot `execute`.

---

## 2. The pipeline (one farmer message)

```
farmer text/voice
      |
      v
 COLLECT  orchestrator -> intake.understand          intent + entities (+ confidence)
      |   low confidence? -> responder asks a clarifying question (never guesses)
      v
 FETCH    orchestrator -> investigator.investigate   portal read + rules -> findings
      |   NOT_FOUND vs PORTAL_DOWN/TIMEOUT are different answers
      v
 DECIDE   orchestrator (plain code)                  report / propose / ask / UNCERTAIN
      |
      +--> nothing to change -> RESPOND
      v
 PROPOSE  orchestrator -> action.propose             proposal with base record_version + idempotency key
      v
 AWAIT_APPROVAL   farmer says yes/no (or taps a button)
      v
 EXECUTE  orchestrator -> action.decide, action.execute     exactly once; timeout -> check portal before retry
      v
 VERIFY   orchestrator -> verifier.verify            fresh portal read: VERIFIED / FAILED / PENDING / UNCERTAIN
      v
 RESPOND  orchestrator -> responder.compose          (auditor.record at every step)
```

Every reply includes its `trace` (for example `COLLECT > FETCH > DECIDE > PROPOSE > AWAIT_APPROVAL > RESPOND`).
The UI and the judge console show it.

---

## 3. Walkthrough: TC3, season correction (real messages from TEST_EVIDENCE.md)

**Farmer:** *"mera rabi 2026-27 ka claim KRB-2026-00633 ka status batao"*

```
orchestrator -> intake: understand          (text=mera rabi 2026-27 ka claim ...)
intake -> orchestrator: understand.result   (intent=check_status, confidence=0.975,
                                             entities={app_no: KRB-2026-00633, season: Rabi 2026-27})
orchestrator -> investigator: investigate   (app_no=KRB-2026-00633, stated_season=Rabi 2026-27)
investigator -> orchestrator: investigate.result (fetch=FOUND, record_version=1, season_mismatch=True, ...)
orchestrator -> responder: compose          (key=status ...)            -> status text in Hindi
orchestrator -> action: propose             (season_change, value=Rabi 2026-27)
action -> orchestrator: propose.result      (proposal act-..., base_version=1, idempotency key)
orchestrator -> responder: compose          (key=propose_season ...)    -> "क्या मैं सीज़न बदलकर Rabi 2026-27 कर दूँ?"
```
State is now `AWAIT_APPROVAL`, and **the portal is unchanged** (the test checks this).

**Farmer:** *"haan kar do"*

```
orchestrator -> intake: understand          -> intent=approve (0.983)
orchestrator -> action: decide              (approve=True)        PENDING -> APPROVED
orchestrator -> action: execute             -> re-reads version, POSTs once with expected_version + key -> EXECUTED
orchestrator -> verifier: verify            -> fresh GET: expected {season: Rabi 2026-27}, observed {season: Rabi 2026-27} -> VERIFIED
orchestrator -> action: attach_verification
orchestrator -> responder: compose          (key=verified)        -> "हो गया और जाँच भी हो गई ..."
```

Where each decision happens in code:
- **The intent** comes from [IntakeAgent.on_understand](../agent/agents.py#L42), which calls
  [predict()](../agent/nlu/predict.py#L27). The 0.45 confidence threshold is at
  [predict.py#L13](../agent/nlu/predict.py#L13).
- **Mismatch and payment rules** are in [rules.assess_claim](../agent/rules.py#L59) and
  [rules.payment_state](../agent/rules.py#L48).
- **"What next?"** is decided in [Orchestrator._claim_flow](../agent/planner.py#L145).
- **The approval to execute to verify chain** is in
  [Orchestrator._decide](../agent/planner.py#L216).
- **The exactly-once execution** is in [ActionRunner._execute_once](../agent/approvals.py#L85).
- **The independent check** is in [verify.verify](../agent/verify.py#L13).

---

## 4. Safety guarantees and where they are enforced

| Guarantee | Enforced in | Proven by |
|---|---|---|
| Nothing changes without the farmer's approval | `ActionRunner.run` refuses unless APPROVED ([approvals.py](../agent/approvals.py)) | `test_cannot_execute_without_approval`, TC2/TC3 "portal unchanged before approval" |
| Only the owner session can approve | `ApprovalStore.get` checks the session ([approvals.py#L42](../agent/approvals.py#L42)) | `test_sessions_are_isolated`, `test_approve_endpoint_flow_and_isolation` |
| Reject means no change | `action.decide(approve=False)` | F4 |
| Exactly once (double click, retries) | per-proposal lock + `EXECUTED` replay + portal `idempotency_key` | F5, `test_concurrent_double_click_executes_once` |
| On timeout, check before retrying | [approvals.py#L113](../agent/approvals.py#L113) | F6, `test_timeout_unknown_then_check_before_retry` |
| Stale proposal expires | `record_version != base_version` → EXPIRED ([approvals.py#L98](../agent/approvals.py#L98)) | F9 |
| An attempt is never proof | separate **verifier** agent (maker-checker) | F7 (`drop_writes` → FAILED), `test_maker_checker_executor_never_verifies` |
| Approved ≠ paid | `rules.payment_state` | TC4, F8 |
| Missing or contradictory data → UNCERTAIN | `rules.assess_claim` | F3, `test_missing_field_is_uncertain` |
| Not found ≠ portal down | `rules.classify_fetch` + different replies | F2 |
| Exact document names | `rules.missing_documents` copies the portal list | TC2 |
| Every decision explained, no secrets | auditor agent + `evidence._scrub` | `test_evidence_never_stores_secrets`, `test_transcript_redacts_secrets` |

---

## 5. Design choices (and why)

**Why multi-agent?** Each agent has one job and its own tools, which brings three benefits:
1. **Separation of duties.** The agent that makes a change (action) is never the agent that
   confirms it (verifier). That's the same maker-checker rule banks use.
2. **Narrow jobs.** Only the action agent uses the portal's write tools. The investigator and
   verifier only read, and intake has no portal access at all. Each agent accepts only its own
   message types, so the verifier refuses an `execute` request. (A stricter version would hand
   the readers a read-only client.)
3. **Replaceability.** Swapping the NLU for a bigger model touches only the intake agent.

**Why is the orchestrator a state machine, not an LLM?** The brief said no LLMs and no APIs.
More importantly, insurance changes must be *auditable*. Our trained model decides only
**what the farmer wants**. Everything with consequences is plain, tested code: which agent
acts, what is allowed, and when to stop.

**Why our own small model?** Free, offline, fast (milliseconds), and trained from scratch on
2,035 synthetic EN/HI/Hinglish utterances. It reaches 99.5% on held-out data and 96.7% on
unseen phrasings. Character n-grams handle Devanagari, Hinglish, typos and speech-to-text
errors.

**Why is the message bus synchronous and in-process?** It's simple, deterministic, easy to
test, and works on serverless hosting. Agents could move to separate processes later,
because they already communicate only through messages.

---

## 6. Likely interview questions

1. **"Is this really agentic?"** Yes. It understands a goal, plans the next step, uses tools
   (portal read/write, help booking), acts autonomously within limits (human approval for
   changes), checks its own results with an independent verifier, and explains itself through
   the evidence log.
2. **"Where is the AI?"** In the intake agent: a TF-IDF character n-gram + LogisticRegression
   intent classifier trained by us (`agent/nlu/train.py`), plus rule-based entity extraction.
   Below 0.45 confidence it asks rather than guesses.
3. **"What happens if the farmer double-clicks Approve?"** The second click finds the
   proposal already `EXECUTED` and gets the first result back. The portal also deduplicates
   by `idempotency_key`. (F5)
4. **"And if the portal times out mid-write?"** The action agent re-reads the portal *before*
   any retry. If the change is there, nothing more is sent. If not, it retries once with the
   same idempotency key. If the outcome is still unknown, the proposal becomes
   `PENDING_CONFIRMATION` and can't be cancelled, because it might already be applied. (F6)
5. **"What if someone else edits the record between proposal and approval?"** The proposal
   stores `base_version`. If the portal's `record_version` changed, it expires and nothing
   changes. (F9)
6. **"How do you know a change worked?"** The verifier agent does a fresh read and compares
   expected with observed. The executor's own "ok" is never trusted. (F7 shows a portal that
   says ok but saved nothing, and the verifier catches it.)
7. **"Can the model hallucinate a document name?"** No. Replies come from fixed templates,
   and document names are copied from the portal response.
8. **"How do you stop one farmer approving another's change?"** Proposals belong to a
   session, and `ApprovalStore.get` refuses other sessions (HTTP 403).
9. **"How is the system tested?"** 113 pytest tests cover the rules, NLU, agents, safety,
   API and accounts. The 13 end-to-end scenarios run in pytest, `run_tests.py`
   (→ TEST_EVIDENCE.md) and the live judge console, and all check against a direct portal read.
10. **"Limitations?"** The template-trained NLU can miss unusual phrasing (it then asks
    again). State is in memory, so it resets on restart, and on serverless hosting it is
    per instance. Document checks cover quality only, not authenticity. The VerbX voice
    adapter is a stub.

---

## 7. Live demo checklist

1. Open https://kisan-claim-mitra.vercel.app/console.html and show the **agents on the message bus**.
2. Press **Run all 4 tests**, click **TC3**, and walk through the **Agent conversation** panel
   using section 3 above.
3. Press **Run failure cases** and click **F5** (double click), **F6** (timeout) and **F7**
   (verification failure).
4. On the farmer app (https://kisan-claim-mitra.vercel.app), say or type TC2 or TC4 live,
   then refresh the console's **Live agent conversation** to show the same agents at work.
