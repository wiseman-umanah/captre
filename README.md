# Captre

**On-chain first-claim attestation — anchored on Algorand, paid via x402.**

Captre lets any agent or system prove it produced a piece of content *before* anyone else. A SHA-256 hash is anchored in Algorand Box Storage; the payer's address is recorded permanently as the author. The claim is immutable — revocation marks it as retracted but does not reopen the hash to new claimants.

Live demo: **https://captre.onrender.com** · API docs: **/api-reference**

---

## How it works

```
Client                      Captre (FastAPI)               Algorand
  │                              │                              │
  │  POST /attest                │                              │
  │──────────────────────────────▶  402 Payment Required        │
  │◀─────────────────────────────│  (challenge in header)       │
  │                              │                              │
  │  POST /attest + USDC payment │                              │
  │──────────────────────────────▶  facilitator verifies        │
  │                              │──────────────────────────────▶ app call
  │                              │                              │  box write
  │  201 {attestation_id, …}     │                              │
  │◀─────────────────────────────│                              │
```

1. Client sends `POST /attest` — receives a `402` with an ALGO/USDC payment challenge.
2. Client signs and sends back the payment — the [GoPlausible facilitator](https://facilitator.goplausible.xyz) verifies it on-chain.
3. Captre's service account submits the AVM app call, writing the attestation to Box Storage.
4. The payer's address (from the x402 payment payload) is recorded as `author` — **never** from `Txn.sender()`.

Verification (`GET /verify`, `GET /attestation/:id`) is always **free**.

---

## API

| Method | Path | Cost | Description |
|--------|------|------|-------------|
| `POST` | `/attest` | $0.05 USDC | Create a first-claim attestation |
| `POST` | `/revoke` | $0.05 USDC | Revoke (original author only) |
| `GET` | `/verify?content_hash=…` | free | Lookup by content hash |
| `GET` | `/attestation/{id}` | free | Lookup by UUID or content hash |
| `GET` | `/health` | free | Liveness check |

### Attest

```http
POST /attest
Content-Type: application/json

{
  "content_hash": "sha256:abc123...",
  "agent_id":     "my-agent-v1",        // optional
  "output_type":  "research",           // research|file|decision|code|report|other
  "description":  "Q3 climate analysis",
  "model":        "gpt-4o",
  "tags":         ["climate", "v1"],
  "previous_attestation": null
}
```

Response `200`:
```json
{
  "attestation": {
    "attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4",
    "author":         "GFYF3KD...",
    "content_hash":   "sha256:abc123...",
    "status":         "active",
    "tx_id":          "QK5ATJT...",
    "created_at":     "2025-01-01T00:00:00Z"
  },
  "message": "Attestation created successfully"
}
```

Error `409` — hash already claimed:
```json
{
  "error": "content_hash already claimed",
  "existing_attestation": { ... }
}
```

### Revoke

```http
POST /revoke
Content-Type: application/json

{ "attestation_id": "a00fe88e-c4fa-4d4a-92d6-043af786e4b4" }
```

- Only the wallet that paid for `/attest` can revoke. `403` is returned otherwise.
- The hash is permanently closed — revoked attestations remain on-chain and visible.
- `attestation_id` may be a UUID *or* the raw `content_hash`.

---

## On-chain storage

The contract uses two Algorand BoxMaps:

| BoxMap | Key | Value |
|--------|-----|-------|
| `attestations` | `sha256(content_hash_string)` — 32 bytes | Full JSON attestation blob |
| `id_index` | `attestation_id` UUID — 36 bytes | Original `content_hash` string |

Box names stay well under the 64-byte AVM limit (`b"a:" + 32 bytes` = 34 bytes). Both boxes are written atomically in a single `attest()` call.

---

## Local development

### Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), [AlgoKit CLI](https://developer.algorand.org/docs/get-details/algokit/)
- A funded testnet wallet (`DEPLOYER_MNEMONIC` / `SERVICE_MNEMONIC`)
- The wallet must hold testnet USDC (ASA `10458941`) at `RECEIVER_ADDRESS` — this is where attestation payments land

### 1. Install

```bash
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# fill in DEPLOYER_MNEMONIC, SERVICE_MNEMONIC, RECEIVER_ADDRESS
```

Key variables:

| Variable | Description |
|----------|-------------|
| `ALGOD_URL` | Algorand node — defaults to public testnet |
| `DEPLOYER_MNEMONIC` | 25-word mnemonic used to deploy the contract |
| `SERVICE_MNEMONIC` | 25-word mnemonic used to submit on-chain app calls |
| `RECEIVER_ADDRESS` | Algorand address that receives x402 USDC payments |
| `APP_ID` | Written automatically by deploy script |
| `ATTEST_PRICE` | Defaults to `$0.05` |
| `REVOKE_PRICE` | Defaults to `$0.05` |

### 3. Deploy the contract

```bash
uv run python -m captre.contract.deploy
```

This writes `APP_ID` and `APP_ADDRESS` back to `.env`. The contract account must be funded for Box MBR (minimum balance reserve) before any attestation will succeed — top it up with a small ALGO transfer to `APP_ADDRESS`.

If the contract ABI changes and cannot be updated in place, use the fresh-deploy path:

```bash
uv run python -m captre.contract._fresh_deploy
```

### 4. Run the server

```bash
uv run captre          # hot-reload dev server on :8000
```

---

## Testing

```bash
uv run pytest tests/unit/                           # all unit tests (no chain needed)
uv run pytest tests/unit/test_attest_endpoint.py    # single file
uv run pytest tests/unit/test_attest_endpoint.py::test_attest_success_returns_200  # single test

uv run pytest tests/integration/                    # live testnet — requires .env
```

```bash
uv run ruff check .    # lint
uv run ruff format .   # format
```

---

## Project structure

```
src/captre/
├── api/
│   ├── attest.py          # POST /attest — x402-paid
│   ├── revoke.py          # POST /revoke — x402-paid, author-only
│   └── verify.py          # GET /verify, GET /attestation/:id — free
├── contract/
│   ├── captre_app.py      # Algorand Python smart contract (AlgoKit/Puya)
│   ├── deploy.py          # Reuse-or-deploy script
│   ├── _fresh_deploy.py   # Force new app when ABI/schema changes
│   └── artifacts/         # Compiled ARC-56 + TEAL (generated)
├── settlement/
│   └── write_attestation.py  # Payment settle → box write (sequential)
├── ui/
│   ├── static/style.css
│   └── templates/         # Jinja2 templates
├── __init__.py            # App factory, x402 middleware wiring
├── models.py              # Pydantic schemas
└── x402_config.py         # Route configs, pricing, Bazaar discovery
```

---

## Deployment (Render)

1. Set all `.env` variables as Render environment variables.
2. Add a Persistent Disk mounted at `/data`; set `INDEX_DB_PATH=/data/index.db`. (optional)
3. Start command: `uv run captre`.
4. Deploy contract once, copy `APP_ID` into the Render env vars.
5. Ensure `APP_ADDRESS` has enough ALGO for Box MBR before first attestation.

---

## Agents demo

See [`agents/README.md`](agents/README.md) for a standalone multi-agent world simulation that exercises every endpoint concurrently across four distinct AI agents.
