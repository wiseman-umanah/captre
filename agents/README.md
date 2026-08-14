# Captre Agent World

A standalone simulation of four AI agents operating concurrently on the [Captre](https://captre.onrender.com) on-chain attestation platform. No code is imported from the main Captre app — agents communicate with the server over HTTP only, paying with real testnet USDC.

---

## What each agent does

| Agent | Role | Actions |
|-------|------|---------|
| **RESEARCHER** | Produces research summaries | Attests 3 findings, revokes 1 (retraction) |
| **CODER** | Produces code artefacts | Attests 3 snippets with version lineage chain |
| **AUDITOR** | Verifies others' claims | Verifies all registry items (free), attests audit report |
| **CRITIC** | Issues & retracts decisions | Attests a decision, revokes it, attests correction |

All four agents run **concurrently** from a single command. Terminal output is a colour-coded log of every on-chain action across all agents in real time.

---

## Architecture

```
agents/
├── world.py              ← entry point — run this
├── agents.json           ← generated on first run (agent wallets — keep safe)
├── .env                  ← local config (not committed)
├── shared/
│   ├── wallet.py         ← AlgorandWallet (implements x402 ClientAvmSigner)
│   ├── bank.py           ← funds all agents from one bank wallet
│   ├── captre_client.py  ← HTTP wrapper: attest / revoke / verify with x402 payment
│   ├── hashing.py        ← sha256 content-hash helper
│   └── log.py            ← colour-coded terminal logger (one colour per agent)
└── agents/
    ├── researcher.py
    ├── coder.py
    ├── auditor.py
    └── critic.py
```

---

## Setup

### 1. Install dependencies

```bash
cd agents/
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
CAPTRE_BASE_URL=http://localhost:8000   # or https://captre.onrender.com
BANK_MNEMONIC=word word word ...        # 25-word Algorand mnemonic for the bank wallet
ALGOD_URL=https://testnet-api.algonode.cloud
USDC_ASSET_ID=10458941                  # testnet USDC ASA ID
```

### 3. Fund the bank wallet

The address derived from `BANK_MNEMONIC` needs:

- **Testnet ALGO** — ~2 ALGO covers MBR + gas for all 4 agents  
  → [Algorand Testnet Dispenser](https://bank.testnet.algorand.network/)
- **Testnet USDC** (ASA `10458941`) — ~2 USDC covers all attests + revokes  
  → Swap on [Tinyman testnet](https://testnet.tinyman.org/)

The bank wallet auto-opts into USDC and auto-funds each agent before the simulation starts.

### 4. Run

```bash
cd agents/
uv run python world.py
```

On first run four agent wallets are generated and saved to `agents.json`. The bank tops up each wallet with ALGO and USDC. Then all agents run concurrently.

**Re-runs** reuse the same wallets and skip funding if balances are already sufficient. Delete `agents.json` to reset and generate fresh wallets.

---

## How x402 payment works

Each agent holds its own Algorand wallet. When an agent calls `POST /attest`:

1. Captre responds `402 Payment Required` — the payment challenge arrives in the `payment-required` header as base64-encoded JSON.
2. The agent's `AlgorandWallet` (which implements the `ClientAvmSigner` protocol) builds and signs a USDC transfer transaction group.
3. The signed payment is sent back as `PAYMENT-SIGNATURE` in the retry request header.
4. The [GoPlausible facilitator](https://facilitator.goplausible.xyz) verifies and settles the payment on-chain.
5. Captre writes the attestation box — the **agent's own Algorand address** is permanently recorded as `author`.

Every agent is a distinct, cryptographically-identified actor on-chain.

---

## One bank, many agents

Rather than manually funding every wallet, `world.py` uses a single `BANK_MNEMONIC` to:

1. Check each agent's ALGO balance and top up only what is needed
2. Opt each agent into the USDC ASA if not already opted in
3. Check each agent's USDC balance and top up only what is needed

This all happens automatically before the simulation starts. The bank only sends what is missing — re-runs that don't need funding skip the transfers entirely.

---

## Running against the live server

Set `CAPTRE_BASE_URL=https://captre.onrender.com` in `.env`. Everything else is the same — agents pay real testnet USDC and write real on-chain attestations. Results are visible at `https://captre.onrender.com/explore`.
