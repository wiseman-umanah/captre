# Full Ledger Platform Plan

## Overview

Transform Captre from a first-claim hash registry into a full provenance ledger
proving the complete chain: **task → output → evaluation → settlement**.

**Design principle:** Permanent proof of output is useful only if provenance
distinguishes creation from acceptance. The ledger must record the task hash,
policy version, evaluator identity, and settlement result — and every link in
the chain must be cryptographically bound, not self-reported. Private inputs
stay off-chain; only hashes and identities go on-chain.

**Key constraint discovered:** The existing `CaptreApp` contract on mainnet
(`APP_ID=3682418169`) has 25 ALGO inside it and cannot be updated or deleted
(approval program rejects `OnCompletion != NoOp`). All new features are built
as **separate contracts** that reference attestations from the existing one by ID.

### Architecture

```
CaptreApp (existing — untouched)      TaskApp (new)        LedgerApp (new)
APP_ID=3682418169                      APP_ID=<new>          APP_ID=<new>
attestations BoxMap b"a:"              tasks BoxMap b"t:"    evaluations BoxMap b"e:"
id_index BoxMap b"i:"
  ↑ POST /attest (existing, x402 $0.05)   ↑ POST /submit-task    ↑ POST /evaluate
  ↑ POST /revoke (existing, x402 $0.05)   ↑ GET /task/:id        ↑ GET /evaluation/:id
  ↑ GET /verify  (existing, free)         (x402 $0.01 paid)      (x402 $0.01 paid)
                                                                  cross-calls CaptreApp.exists()
                                                                  cross-calls TaskApp.task_exists()
```

### Chain of proof

```
TaskRecord  ──── task_hash ────▶  Attestation  ──── output_attestation_id ────▶  EvaluationRecord
  author (payer)                    author (payer)                                  evaluator (payer)
  task_hash (SHA-256 of content)    task_hash (must match real TaskRecord)          policy_hash (SHA-256 of policy doc)
  tx_id (x402 payment)              policy_version                                  evaluation_result
                                    tx_id (x402 payment)                            score
                                                                                    tx_id (x402 payment)
```

Every node in the chain:
- Is authored by a **wallet that paid** (x402 payer, not self-reported address)
- References the previous node by hash or ID
- The reference is **verified on-chain** by LedgerApp before writing

### What changes

| Layer | Change |
|---|---|
| Contracts | Two new contracts: `TaskApp` and `LedgerApp` — both with update/delete methods |
| Contracts | `LedgerApp.add_evaluation` cross-calls BOTH `CaptreApp.exists()` AND `TaskApp.task_exists()` |
| Models | New `TaskRecord`, `EvaluationRecord`; extend `Attestation`/`AttestRequest` with `task_hash`, `content_cid`, `policy_version` |
| Models | `EvaluateRequest.evaluator` removed — evaluator identity comes from x402 payer only |
| Models | `EvaluationRecord.policy_hash` stores `sha256:<hash>` of the policy document, not a label |
| Settlement | New `write_task.py` and `write_evaluation.py` |
| Settlement | `write_attestation.py` verifies `task_hash` resolves to a real `TaskRecord` when supplied |
| API | `POST /submit-task` (x402 $0.01), `GET /task/:id` (free) |
| API | `POST /evaluate` **(x402 $0.01 — not free)**, `GET /evaluation/:id` (free) |
| x402 config | Add `POST /submit-task` and `POST /evaluate` to `ROUTES_CONFIG` |
| App factory | Register new routers before `ui_router` |
| `.env` | Add `TASK_APP_ID`, `TASK_APP_ADDRESS`, `LEDGER_APP_ID`, `LEDGER_APP_ADDRESS`, `SUBMIT_TASK_PRICE`, `EVALUATE_PRICE` |
| Deploy | Two fresh deploys (TaskApp + LedgerApp), each pre-funded with 2 ALGO |

### What does NOT change

- `CaptreApp` source, artifacts, deployment — untouched
- `write_attestation.py` core logic — only `write_attestation()` gains an optional guard for `task_hash`
- `/attest`, `/revoke`, `/verify` endpoints — untouched
- All existing tests — continue to pass

---

## Sub-Tasks

---

### Sub-Task 1 — TaskApp and LedgerApp contracts

**Status:** `[~] in progress` (contracts written + compiled; deploy pending)

**Intent:**
Write two new Algorand Python contracts. `TaskApp` stores task submissions
independently. `LedgerApp` stores evaluation records and cross-calls BOTH
`CaptreApp.exists()` AND `TaskApp.task_exists()` before writing — this is
what makes the ledger prove correctness, not just storage.

**What is already done:**
- `src/captre/contract/task_app.py` — written and compiled ✅
- `src/captre/contract/ledger_app.py` — written and compiled (see divergence note below) ✅
- `src/captre/contract/artifacts/TaskApp.arc56.json` — compiled ✅
- `src/captre/contract/artifacts/LedgerApp.arc56.json` — compiled ✅
- `src/captre/contract/deploy_task.py` — written ✅
- `src/captre/contract/deploy_ledger.py` — written ✅
- `pyproject.toml` — `captre-deploy-task` and `captre-deploy-ledger` entries added ✅
- `.env.example` — `TASK_APP_ID`, `TASK_APP_ADDRESS`, `LEDGER_APP_ID`, `LEDGER_APP_ADDRESS` added ✅

**Divergence to fix before deploying:**

The plan originally said `add_evaluation` takes 4 args. The built version takes
5 args (adds `evaluation_id_str`). More importantly, the cross-contract check
only validates `CaptreApp.exists()` — it does NOT cross-call `TaskApp.task_exists()`.
This must be fixed before deploying. See correctness gap analysis:

- `add_evaluation` should drop `evaluation_id_str` (no second box like `id_index` — no need)
- `add_evaluation` must also cross-call `TaskApp.task_exists(task_hash_key)` when a
  non-zero `task_hash_key` is supplied, asserting `ERR_TASK_NOT_FOUND` if false
- `task_hash_key` becomes a required arg to `add_evaluation` (32 bytes or zero-length
  to skip the check for evaluations not linked to a task)

**Revised `add_evaluation` signature (4 args):**
```python
def add_evaluation(
    self,
    attestation_app_id: UInt64,   # CaptreApp app ID
    task_app_id: UInt64,           # TaskApp app ID (pass 0 to skip task check)
    content_hash_key: Bytes,       # 32-byte key for CaptreApp.exists()
    task_hash_key: Bytes,          # 32-byte key for TaskApp.task_exists() — b"" to skip
    evaluation_id_key: Bytes,      # 32-byte SHA-256 of evaluation UUID — box key
    metadata_json: Bytes,          # full EvaluationRecord JSON
) -> None
```

**Revised `get_evaluation` signature (unchanged — takes digest key):**
```python
def get_evaluation(self, evaluation_id_key: Bytes) -> Bytes
```

**Remaining Todo List:**
1. Update `src/captre/contract/ledger_app.py` — fix `add_evaluation` signature (drop `evaluation_id_str`, add `task_app_id` + `task_hash_key`, add second cross-call to `TaskApp.task_exists()`)
2. Recompile `ledger_app.py` via isolation workaround, copy artifacts
3. Deploy `TaskApp` to mainnet: `uv run captre-deploy-task`
4. Deploy `LedgerApp` to mainnet: `uv run captre-deploy-ledger`
5. Fund both contract addresses with ≥2 ALGO
6. Write `.env` with new `TASK_APP_ID`, `TASK_APP_ADDRESS`, `LEDGER_APP_ID`, `LEDGER_APP_ADDRESS`

**Relevant Context:**
- `arc4.abi_call[ABIBool]("task_exists(byte[])bool", ...)` — same pattern as the existing CaptreApp cross-call
- `task_app_id=0` path: `if task_hash_key.length > UInt64(0): ...cross-call...` — only check when non-empty
- Box key for evaluations: `b"e:" + SHA-256(evaluation_uuid)` — 34 bytes, under 64-byte limit
- Both cross-called apps must be in `foreignApps` on the transaction

---

### Sub-Task 2 — Extend models

**Status:** `[ ] pending`

**Intent:**
Add `TaskRecord`, `EvaluationRecord`, and their request/response types to
`models.py`. The critical correctness fix here is:

1. `EvaluateRequest` has **no `evaluator` field** — evaluator identity comes from
   the x402 payment payer address, just like `author` in `AttestRequest`.
2. `EvaluationRecord` stores `policy_hash: str` (a `sha256:...` string of the
   policy document), not just a `policy_version` label string. The caller
   is responsible for hashing their policy document before submitting.
3. `Attestation` gains `task_hash: str | None` — stored in the on-chain JSON.
   When supplied, `write_attestation()` verifies it resolves to a real `TaskRecord`.

**Expected Outcomes:**
- `EvaluationResult` enum: `pass_`, `fail`, `partial`, `score_only`
- `AttestRequest` gains: `task_hash: str | None`, `content_cid: str | None`, `policy_version: str | None`
- `Attestation` gains same three optional fields (stored in on-chain JSON blob)
- `SubmitTaskRequest`: `content: str`, `agent_id: str | None`, `description: str | None`, `tags: list[str]`, `extra: dict`
- `TaskRecord`: `task_id`, `author` (from x402 payer), `created_at`, `tx_id`, `task_hash`, `task_cid: str | None`, `agent_id`, `description`, `tags`, `extra`
- `SubmitTaskResponse`: wraps `TaskRecord` + `message`
- `EvaluateRequest`: `output_attestation_id`, `content_hash`, `task_hash: str | None`, `policy_hash: str`, `evaluation_result: EvaluationResult`, `score: float | None`, `notes: str | None`
  - **No `evaluator` field** — comes from x402 payer
  - `policy_hash` is required, formatted as `sha256:<64 hex chars>`
- `EvaluationRecord`: `evaluation_id`, `created_at`, `output_attestation_id`, `content_hash`, `task_hash: str | None`, `evaluator` (from x402 payer), `policy_hash`, `evaluation_result`, `score: float | None`, `tx_id`
- `EvaluateResponse`: wraps `EvaluationRecord` + `message`
- All models have NumPy docstrings with `Attributes` section
- Existing tests continue to pass; new model tests added to `tests/unit/test_models.py`

**Todo List:**
1. Add `EvaluationResult` enum to `src/captre/models.py`
2. Add three optional fields to `AttestRequest` and `Attestation`
3. Add `SubmitTaskRequest`, `TaskRecord`, `SubmitTaskResponse`
4. Add `EvaluateRequest` (no evaluator field), `EvaluationRecord`, `EvaluateResponse`
5. Add tests for new models to `tests/unit/test_models.py`

**Relevant Context:**
- `src/captre/models.py` — use `X | None` not `Optional[X]`; Pydantic v2 syntax
- Field names are on-chain JSON keys — once deployed, cannot be renamed
- `policy_hash` must be validated as `sha256:` prefix — add a Pydantic `field_validator`

---

### Sub-Task 3 — Task settlement layer

**Status:** `[ ] pending`

**Intent:**
Create `src/captre/settlement/write_task.py`. Mirrors `write_attestation.py`
patterns exactly: module-level singletons for the `TaskApp` client, sync
functions + async wrappers, same error handling conventions.

**Expected Outcomes:**
- `src/captre/settlement/write_task.py` with:
  - `_task_hash_key(task_content: str) -> bytes` — SHA-256 of content string
  - `write_task(request: SubmitTaskRequest, payer_address: str, payment_tx_id: str) -> TaskRecord`
  - `write_task_async(...)` — `asyncio.to_thread` wrapper
  - `read_task_from_box(task_hash: str) -> TaskRecord | None`
  - `read_task_from_box_async(...)` — async wrapper
- `ValueError` on duplicate task hash (`ERR_ALREADY_CLAIMED`)
- `RuntimeError` on box write failure after payment settled
- Reuses `_get_algod_client()`, `_get_service_account()`, `_get_algorand_client()` imported from `write_attestation.py` — does NOT re-declare singletons
- Full NumPy docstrings

**Todo List:**
1. Create `src/captre/settlement/write_task.py`
2. Import singleton getters from `write_attestation.py`
3. Implement `_get_task_app_id()` and `_get_task_app_client()` reading `TASK_APP_ID`
4. Implement `_task_hash_key()`
5. Implement `write_task()` and `read_task_from_box()`
6. Implement async wrappers
7. Write `tests/unit/test_write_task.py` mocking the AVM call

**Relevant Context:**
- `write_attestation.py:283-386` — `write_attestation()` as reference implementation
- `write_attestation.py:477-519` — `read_attestation_from_box()` as reference
- `BoxReference` must include full prefix: `name=b"t:" + task_hash_key`
- algokit wraps `LogicError` in `ValueError` — walk full chain to find `ERR_ALREADY_CLAIMED`
- `task_hash_key = SHA-256(request.content)` — hash the raw content string, not a hash-of-hash

---

### Sub-Task 4 — Evaluation settlement layer

**Status:** `[ ] pending`

**Intent:**
Create `src/captre/settlement/write_evaluation.py`. Evaluations are x402
**paid** (not free) — `payer_address` comes from the x402 payment payload
and becomes `evaluator` in the stored record. Before writing, the Python
layer verifies the attestation exists; the AVM layer additionally cross-calls
`CaptreApp.exists()` and (if `task_hash` is set) `TaskApp.task_exists()`.

**Expected Outcomes:**
- `src/captre/settlement/write_evaluation.py` with:
  - `_evaluation_id_key(evaluation_id: str) -> bytes` — SHA-256 of the UUID string
  - `_task_hash_key_from_hash(task_hash: str) -> bytes` — SHA-256 of the task hash string (same as `write_task._task_hash_key` but takes the stored `task_hash` field, not raw content)
  - `write_evaluation(request: EvaluateRequest, payer_address: str, payment_tx_id: str) -> EvaluationRecord`
  - `write_evaluation_async(...)` — async wrapper
  - `read_evaluation_from_box(evaluation_id: str) -> EvaluationRecord | None`
  - `read_evaluation_from_box_async(...)` — async wrapper
- Box key: `SHA-256(evaluation_uuid)` — one evaluation per UUID, unique by construction
- Guards (Python layer, before AVM call):
  - `read_attestation_from_box(content_hash)` returns `None` → `ValueError("attestation not found")`
  - If `request.task_hash` is set: `read_task_from_box(task_hash)` returns `None` → `ValueError("task not found")`
- AVM layer guards (in `LedgerApp.add_evaluation`):
  - `CaptreApp.exists(content_hash_key)` → `ERR_ATTESTATION_NOT_FOUND`
  - `TaskApp.task_exists(task_hash_key)` → `ERR_TASK_NOT_FOUND` (when `task_hash_key` non-empty)
- `payer_address` becomes `EvaluationRecord.evaluator` — never from request body
- Full NumPy docstrings

**Todo List:**
1. Create `src/captre/settlement/write_evaluation.py`
2. Implement `_get_ledger_app_id()` and `_get_ledger_app_client()` reading `LEDGER_APP_ID`
3. Implement `_evaluation_id_key()` and `_task_hash_key_from_hash()`
4. Implement `write_evaluation()` — Python guards first, then AVM call with both `foreignApps`
5. Implement `read_evaluation_from_box()`
6. Implement async wrappers
7. Write `tests/unit/test_write_evaluation.py`

**Relevant Context:**
- `read_attestation_from_box()` and `read_task_from_box()` are the Python-layer guards
- `LedgerApp.add_evaluation` args: `(attestation_app_id, task_app_id, content_hash_key, task_hash_key, evaluation_id_key, metadata_json)`
- Pass `task_hash_key = b""` (empty Bytes) when `request.task_hash` is None — contract skips check
- `foreignApps` must include BOTH `APP_ID` (CaptreApp) and `TASK_APP_ID` (TaskApp)
- Box references: `b"e:" + evaluation_id_key` for the evaluation box; `b"a:" + content_hash_key` for CaptreApp read; `b"t:" + task_hash_key` for TaskApp read

---

### Sub-Task 5 — New API endpoints

**Status:** `[ ] pending`

**Intent:**
Add four new endpoints. `POST /submit-task` and `POST /evaluate` are both
x402 paid — this is what authenticates the submitter and evaluator by their
Algorand wallet, not by a self-reported address field.

**Expected Outcomes:**
- `src/captre/api/submit_task.py` — paid `POST /submit-task`, pattern identical to `attest.py`
- `src/captre/api/task_verify.py` — free `GET /task/:id` lookup
- `src/captre/api/evaluate.py` — paid `POST /evaluate` **(not free)**, pattern identical to `attest.py`; `_extract_payer()` imported from `attest.py`
- `src/captre/api/evaluation_verify.py` — free `GET /evaluation/:id` lookup
- Both `POST /submit-task` and `POST /evaluate` added to `ROUTES_CONFIG` in `x402_config.py`
- All four routers registered in `src/captre/__init__.py` before `ui_router`
- Unit tests for each new endpoint

**Todo List:**
1. Create `src/captre/api/submit_task.py` (paid — follows `attest.py` exactly)
2. Create `src/captre/api/task_verify.py` (free — follows `verify.py` pattern)
3. Create `src/captre/api/evaluate.py` (paid — follows `attest.py`; uses `_extract_payer` from `attest.py`)
4. Create `src/captre/api/evaluation_verify.py` (free)
5. Add `POST /submit-task` and `POST /evaluate` `RouteConfig` entries to `x402_config.py`
6. Add `SUBMIT_TASK_PRICE` and `EVALUATE_PRICE` env vars (default `$0.01`)
7. Register all four routers in `src/captre/__init__.py`
8. Write tests: `test_submit_task_endpoint.py`, `test_evaluate_endpoint.py`

**Relevant Context:**
- `src/captre/api/attest.py` — paid endpoint reference; `_extract_payer()` lives here, import it in `evaluate.py`
- `src/captre/api/verify.py` — free endpoint reference
- `x402_config.py:69-117` — `RouteConfig` construction reference
- `__init__.py` router registration order — all new routers before `ui_router`
- `evaluate.py` mock targets: `captre.api.evaluate._extract_payer` AND `captre.api.attest._extract_payer` — both namespaces need patching in tests (same rule as revoke.py)

---

### Sub-Task 6 — Update UI and API reference

**Status:** `[ ] pending`

**Intent:**
Update Jinja2 templates so the explore/detail UI surfaces the full provenance
chain. The detail page shows the linked task and all evaluations. The API
reference documents all new endpoints and explains the correctness model.

**Expected Outcomes:**
- `detail.html` — shows linked task (task_hash, task_id if resolvable) and evaluations list (evaluator, policy_hash, result, score)
- `explore.html` — evaluation count badge per attestation row
- `api_ref.html` — documents `POST /submit-task`, `POST /evaluate`, `GET /task/:id`, `GET /evaluation/:id`; notes that evaluator identity is proven by x402 payment, not self-reported
- `index.html` — hero updated to describe full provenance chain (task → output → evaluation)
- `src/captre/ui/__init__.py` — `explore_detail()` fetches and passes evaluations

**Todo List:**
1. Update `src/captre/ui/__init__.py` `explore_detail()` to fetch evaluations
2. Update `detail.html`
3. Update `explore.html`
4. Update `api_ref.html`
5. Update `index.html`

**Relevant Context:**
- `templates.TemplateResponse(request, "name.html", ctx)` — request is first positional arg
- `src/captre/ui/static/style.css` — white + amber/orange, zero border-radius, 18px base, Nunito font

---

### Sub-Task 7 — Update AGENTS.md

**Status:** `[ ] pending`

**Intent:**
Update all four AGENTS.md files to reflect the new multi-contract
architecture, new env vars, new mock targets, and corrected factual errors.

**Todo List:**
1. Update `AGENTS.md` — add new env vars, new scripts, updated architecture diagram
2. Update `.bob/rules-agent/AGENTS.md` — add new mock patch targets (evaluate.py), evaluator-from-payer rule
3. Update `.bob/rules-plan/AGENTS.md` — fix "cannot list attestations" error; add multi-contract notes; add correctness-vs-storage distinction
4. Update `.bob/rules-ask/AGENTS.md` — same corrections

---

## Key correctness decisions (do not revert)

| Decision | Reason |
|---|---|
| `POST /evaluate` is x402 paid ($0.01) | Evaluator identity must come from a wallet signature (payment payer), not a self-reported address field. A free endpoint proves storage; a paid endpoint proves the evaluator committed their wallet. |
| `policy_hash` is `sha256:<hash>` not a label | A label like "v2.1" is unbound — anyone can reuse it. A hash of the policy document is immutable. The caller hashes their policy doc; the ledger records that exact commitment. |
| `LedgerApp` cross-calls `TaskApp.task_exists()` | Verifies on-chain that the referenced task was actually submitted, not just that a string was typed. Without this the task→output link is self-reported. |
| `write_attestation()` verifies `task_hash` before writing | Python-layer guard that rejects attestations claiming a `task_hash` that was never submitted. Prevents dangling references in the chain. |
| `evaluation_id_key = SHA-256(evaluation_uuid)` not `SHA-256(attestation_id + evaluator)` | One evaluator can update their evaluation (e.g. rerun with new policy). UUID uniqueness is guaranteed by the server. The evaluator address is still stored in the record and proven by the payment. |
