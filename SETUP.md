# SETUP.md

Step-by-step setup guide for running Captre locally (testnet) or deploying to production (mainnet).

---

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager (`pip install uv` or see uv docs)
- **[AlgoKit CLI](https://developer.algorand.org/docs/get-details/algokit/)** — only needed if you want to recompile the contracts (`pipx install algokit`)
- An **Algorand wallet** with a 25-word mnemonic

---

## 1. Clone and Install

```bash
git clone https://github.com/your-org/captre.git
cd captre
uv sync
```

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in the required values. Reference table below.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `ALGORAND_NETWORK` | yes | `testnet` or `mainnet` |
| `ALGOD_URL` | yes | Algorand node URL (see below) |
| `ALGOD_TOKEN` | no | Leave blank for public nodes |
| `INDEXER_URL` | no | Algorand indexer URL (see below) |
| `DEPLOYER_MNEMONIC` | yes | 25-word mnemonic used to deploy contracts |
| `SERVICE_MNEMONIC` | yes | 25-word mnemonic used to sign all on-chain app calls |
| `RECEIVER_ADDRESS` | yes | Algorand address that receives x402 USDC payments (must match `SERVICE_MNEMONIC`) |
| `APP_ID` | set by deploy | CaptreApp application ID (written by `deploy.py`) |
| `APP_ADDRESS` | set by deploy | CaptreApp contract account address (must be funded) |
| `TASK_APP_ID` | set by deploy | TaskApp application ID |
| `TASK_APP_ADDRESS` | set by deploy | TaskApp contract account address (must be funded) |
| `LEDGER_APP_ID` | set by deploy | LedgerApp application ID |
| `LEDGER_APP_ADDRESS` | set by deploy | LedgerApp contract account address (must be funded) |
| `ATTEST_PRICE` | no | Price per `/attest` call. Default `$0.01` |
| `REVOKE_PRICE` | no | Price per `/revoke` call. Default `$0.01` |
| `SUBMIT_TASK_PRICE` | no | Price per `/submit-task` call. Default `$0.01` |
| `EVALUATE_PRICE` | no | Price per `/evaluate` call. Default `$0.01` |
| `FACILITATOR_URL` | no | x402 facilitator. Default `https://facilitator.goplausible.xyz` — do not change |

**Node URLs:**

| Network | ALGOD_URL | INDEXER_URL |
|---|---|---|
| Testnet | `https://testnet-api.algonode.cloud` | `https://testnet-idx.algonode.cloud` |
| Mainnet | `https://mainnet-api.algonode.cloud` | `https://mainnet-idx.algonode.cloud` |

---

## Option A — Testnet (Development)

No real money. Use the free faucets below.

### Step 1 — Fund your wallet

- **ALGO** (testnet): [bank.testnet.algorand.network](https://bank.testnet.algorand.network/)
- **USDC** (testnet ASA `10458941`): swap on [Tinyman testnet](https://testnet.tinyman.org/)

Make sure `RECEIVER_ADDRESS` is opted into testnet USDC (ASA `10458941`).

### Step 2 — Set `.env` for testnet

```env
ALGORAND_NETWORK=testnet
ALGOD_URL=https://testnet-api.algonode.cloud
INDEXER_URL=https://testnet-idx.algonode.cloud

DEPLOYER_MNEMONIC=word1 word2 ... word25
SERVICE_MNEMONIC=word1 word2 ... word25
RECEIVER_ADDRESS=YOUR_ALGORAND_ADDRESS

ATTEST_PRICE=$0.01
REVOKE_PRICE=$0.01
SUBMIT_TASK_PRICE=$0.01
EVALUATE_PRICE=$0.01
```

### Step 3 — Deploy the contracts

Run each deploy script in order. Each one prints the new app address — **fund it with at least 2 ALGO before running the next one**.

```bash
# Deploy CaptreApp
uv run python -m captre.contract.deploy
# → prints APP_ID and APP_ADDRESS, writes them to .env
# → send at least 2 ALGO to APP_ADDRESS

# Deploy TaskApp
uv run captre-deploy-task
# → prints TASK_APP_ID and TASK_APP_ADDRESS, writes them to .env
# → send at least 2 ALGO to TASK_APP_ADDRESS

# Deploy LedgerApp
uv run captre-deploy-ledger
# → prints LEDGER_APP_ID and LEDGER_APP_ADDRESS, writes them to .env
# → send at least 2 ALGO to LEDGER_APP_ADDRESS
```

> **Why fund the contract accounts?**
> Each box write on Algorand requires a Minimum Balance Reserve (MBR) held in the contract account. Without it, writes will fail. Each attestation/task/evaluation record locks roughly 0.3–0.5 ALGO permanently. 2 ALGO gives you room for several writes before needing to top up.

### Step 4 — Run the server

```bash
uv run captre
```

Server starts on `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

---

## Option B — Mainnet (Production)

Real ALGO and USDC. The three contracts are already deployed on mainnet — **you do not need to deploy them again** unless you are forking the project.

**Existing mainnet contract IDs:**

| Contract | App ID | Contract Address |
|---|---|---|
| CaptreApp | `3682418169` | See Pera Explorer |
| TaskApp | `3709725780` | `4247HOVZ6BSQ6R7Y7JCYAFE5IWJO44QF5G5DJHZUXXC6GP5TOUWSANHHA4` |
| LedgerApp | `3709726556` | `3V4GTE6YL4ZZODEWKEYGV6N4T7SZIHVVZ4ZZG7G44FR2OKTMODFNQGRJF4` |

### Step 1 — Set `.env` for mainnet

```env
ALGORAND_NETWORK=mainnet
ALGOD_URL=https://mainnet-api.algonode.cloud
INDEXER_URL=https://mainnet-idx.algonode.cloud

SERVICE_MNEMONIC=word1 word2 ... word25
RECEIVER_ADDRESS=YOUR_ALGORAND_ADDRESS

APP_ID=3682418169
APP_ADDRESS=<CaptreApp address from Pera Explorer>
TASK_APP_ID=3709725780
TASK_APP_ADDRESS=4247HOVZ6BSQ6R7Y7JCYAFE5IWJO44QF5G5DJHZUXXC6GP5TOUWSANHHA4
LEDGER_APP_ID=3709726556
LEDGER_APP_ADDRESS=3V4GTE6YL4ZZODEWKEYGV6N4T7SZIHVVZ4ZZG7G44FR2OKTMODFNQGRJF4

ATTEST_PRICE=$0.01
REVOKE_PRICE=$0.01
SUBMIT_TASK_PRICE=$0.01
EVALUATE_PRICE=$0.01

FACILITATOR_URL=https://facilitator.goplausible.xyz
```

Make sure `RECEIVER_ADDRESS` is opted into mainnet USDC (ASA `31566704`).

### Step 2 — Monitor contract account balances

Each write drains the contract account. Check balances periodically on [Pera Explorer](https://explorer.perawallet.app) and top up the contract addresses when low.

| Writes planned | ALGO to maintain in each contract account |
|---|---|
| 10 | 3 ALGO |
| 50 | 10 ALGO |
| 200 | 40 ALGO |

### Step 3 — Deploy to Render (or any host)

1. Set all `.env` values above as environment variables in your hosting platform
2. Start command: `uv run captre`
3. *(Optional)* Add a persistent disk at `/data`, set `INDEX_DB_PATH=/data/index.db`

---

## Running Tests

```bash
uv run captre-test                                                # all unit tests
uv run pytest tests/unit/test_attest_endpoint.py::test_name      # single test
uv run pytest tests/integration/                                  # live chain tests (needs .env)
uv run ruff check .                                               # lint
uv run ruff format .                                              # format
```

Unit tests mock everything — no chain, no USDC, no `.env` needed.

---

## Recompiling Contracts

Only needed if you modify the contract source files. Uses an isolation workaround because puyapy cannot walk the full package:

```bash
# CaptreApp
mkdir -p /tmp/captre_compile && \
cp src/captre/contract/captre_app.py /tmp/captre_compile/ && \
algokit compile python /tmp/captre_compile/captre_app.py \
  --out-dir /tmp/captre_compile/artifacts --output-arc32 && \
cp /tmp/captre_compile/artifacts/* src/captre/contract/artifacts/ && \
rm -rf /tmp/captre_compile
```

Replace `captre_app.py` with `task_app.py` or `ledger_app.py` for the other contracts.

---

## Common Issues

**`RuntimeError: APP_ID is not set`**
→ Run `uv run python -m captre.contract.deploy` first, or set `APP_ID` in `.env`.

**`RuntimeError: TASK_APP_ID is not set`**
→ Run `uv run captre-deploy-task` first, or set `TASK_APP_ID` in `.env`.

**`RuntimeError: LEDGER_APP_ID is not set`**
→ Run `uv run captre-deploy-ledger` first, or set `LEDGER_APP_ID` in `.env`.

**Box write fails after payment settled**
→ The contract account is out of ALGO for MBR. Send more ALGO to `APP_ADDRESS` / `TASK_APP_ADDRESS` / `LEDGER_APP_ADDRESS`.

**`KeyError: RECEIVER_ADDRESS`**
→ `RECEIVER_ADDRESS` must be set in `.env`. It is the address that receives USDC payments.

**`transaction rejected by ApprovalProgram` on deploy**
→ An existing contract with the same name was found and the deploy tried to delete it. Clear the existing `APP_ID` from `.env` — the scripts skip deploy when an ID is already set.
