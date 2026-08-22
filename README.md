![captre](image.png)

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
| `POST` | `/attest` | `$ATTEST_PRICE` USDC | Create a first-claim attestation |
| `POST` | `/revoke` | `$REVOKE_PRICE` USDC | Revoke (original author only) |
| `GET` | `/verify?content_hash=…` | free | Lookup by content hash |
| `GET` | `/attestation/{id}` | free | Lookup by UUID or content hash |
| `GET` | `/attestations` | free | List all attestations (newest first) |
| `GET` | `/health` | free | Liveness check |

Price defaults to `$0.05` per call. Override with `ATTEST_PRICE` / `REVOKE_PRICE` in `.env`.

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

Box names stay well under the 64-byte AVM limit (`b"a:" + 32 bytes` = 34 bytes). Both boxes are written atomically in a single `attest()` call. Each attestation costs **~0.277 ALGO** in minimum balance reserve (MBR) locked in the contract account — budget for this when funding `APP_ADDRESS`.

---

## Local development (testnet)

Use testnet for development. No real money involved — use the free dispenser for ALGO and Tinyman testnet for USDC.

### Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), [AlgoKit CLI](https://developer.algorand.org/docs/get-details/algokit/)
- A funded **testnet** wallet (`SERVICE_MNEMONIC`)
- Testnet USDC opted into `RECEIVER_ADDRESS` (ASA `10458941` on testnet)

### 1. Install

```bash
uv sync
```

### 2. Configure for testnet

```bash
cp .env.example .env
```

Set these in `.env`:

```env
ALGORAND_NETWORK=testnet
ALGOD_URL=https://testnet-api.algonode.cloud
ALGOD_TOKEN=
INDEXER_URL=https://testnet-idx.algonode.cloud

DEPLOYER_MNEMONIC=<your 25-word testnet mnemonic>
SERVICE_MNEMONIC=<your 25-word testnet mnemonic>
RECEIVER_ADDRESS=<Algorand address matching SERVICE_MNEMONIC>

ATTEST_PRICE=$0.05
REVOKE_PRICE=$0.05
```

> **Testnet faucets**
> - ALGO: [bank.testnet.algorand.network](https://bank.testnet.algorand.network/)
> - USDC (ASA `10458941`): swap on [Tinyman testnet](https://testnet.tinyman.org/)

### 3. Deploy the contract (testnet)

```bash
uv run python -m captre.contract.deploy
```

The script writes `APP_ID` and `APP_ADDRESS` back to `.env`. Then fund the contract account for Box MBR:

```bash
# send at least 2 ALGO to APP_ADDRESS (copied from .env after deploy)
# each attestation locks ~0.277 ALGO — fund more for sustained use
```

### 4. Run the server

```bash
uv run captre          # hot-reload dev server on :8000
```

---

## Production deployment (mainnet)

Use mainnet for real users and competition leaderboard volume.

### 1. Configure for mainnet

```env
ALGORAND_NETWORK=mainnet
ALGOD_URL=https://mainnet-api.algonode.cloud
ALGOD_TOKEN=
INDEXER_URL=https://mainnet-idx.algonode.cloud

DEPLOYER_MNEMONIC=<your 25-word mainnet mnemonic>
SERVICE_MNEMONIC=<your 25-word mainnet mnemonic>
RECEIVER_ADDRESS=<Algorand address matching SERVICE_MNEMONIC>

ATTEST_PRICE=$0.05
REVOKE_PRICE=$0.05

FACILITATOR_URL=https://facilitator.goplausible.xyz
```

> **Mainnet USDC:** ASA `31566704`. Ensure `RECEIVER_ADDRESS` is opted in before first payment.

### 2. Deploy contract (mainnet)

```bash
ALGORAND_NETWORK=mainnet uv run python -m captre.contract.deploy
```

Copy the printed `APP_ID` and `APP_ADDRESS` into your environment variables.

### 3. Fund the contract account (mainnet)

Each attestation permanently locks ~**0.277 ALGO** in the contract account as Box MBR. Budget accordingly:

| Planned attestations | ALGO to send to `APP_ADDRESS` |
|---|---|
| 30 | ~9 ALGO |
| 90 | ~25 ALGO |
| 300 | ~85 ALGO |

Send the ALGO to `APP_ADDRESS` **before** first attestation. The service will fail with a balance error otherwise.

### 4. Deploy to Render

1. Set all variables above as Render environment variables.
2. *(Optional)* Add a Persistent Disk at `/data`; set `INDEX_DB_PATH=/data/index.db`.
3. Start command: `uv run captre`.

---

## Testing

```bash
uv run pytest tests/unit/                           # all unit tests (no chain, no .env needed)
uv run pytest tests/unit/test_attest_endpoint.py    # single file
uv run pytest tests/unit/test_attest_endpoint.py::test_attest_success_returns_200  # single test

uv run pytest tests/integration/                    # live chain — requires .env with APP_ID set
```

```bash
uv run ruff check .    # lint
uv run ruff format .   # format
uv run pyright         # type check
```

Unit tests mock all chain and payment calls — no ALGO, no USDC, no network required.
Integration tests write real boxes to a live contract. They must be run against testnet first.

---

## Project structure

```
src/captre/
├── api/
│   ├── attest.py          # POST /attest — x402-paid
│   ├── revoke.py          # POST /revoke — x402-paid, author-only
│   └── verify.py          # GET /verify, GET /attestation/:id, GET /attestations — free
├── contract/
│   ├── captre_app.py      # Algorand Python smart contract (AlgoKit/Puya)
│   ├── deploy.py          # Reuse-or-deploy script
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

## Agents demo

See [`agents/README.md`](agents/README.md) for a standalone multi-agent world simulation that exercises every endpoint concurrently across four distinct AI agents — on testnet or mainnet.
