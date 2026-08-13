# Captre Agent World

A standalone simulation of multiple AI agents operating on the [Captre](https://captre.onrender.com) on-chain attestation platform. No code is imported from the main Captre app — this project talks to the server over HTTP only.

## What it demonstrates

| Agent | Role | Actions |
|---|---|---|
| **RESEARCHER** | Produces research summaries | Attests 3 findings, revokes 1 (retraction) |
| **CODER** | Produces code artefacts | Attests 3 snippets with version lineage chain |
| **AUDITOR** | Verifies others' claims | Verifies all registry items (free), attests audit report |
| **CRITIC** | Issues & retracts decisions | Attests a decision, revokes it, attests correction, cross-verifies auditor |

All four agents run **concurrently**. Terminal output is a colour-coded log of every action across all agents.

## Architecture

```
agents/
├── world.py              ← single entry point — run this
├── agents.json           ← generated on first run — agent wallets (keep safe)
├── shared/
│   ├── wallet.py         ← AlgorandWallet (implements x402 ClientAvmSigner)
│   ├── bank.py           ← funds all agents from one bank wallet
│   ├── captre_client.py  ← HTTP wrapper: attest / revoke / verify
│   ├── hashing.py        ← sha256("sha256:<hex>") helper
│   └── log.py            ← rich terminal logger (colour per agent)
└── agents/
    ├── researcher.py
    ├── coder.py
    ├── auditor.py
    └── critic.py
```

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

```
CAPTRE_BASE_URL=http://localhost:8000   # or your deployed Captre URL
BANK_MNEMONIC=word word word ...        # 25-word Algorand mnemonic
ALGOD_URL=https://testnet-api.algonode.cloud
USDC_ASSET_ID=10458941                  # testnet USDC
```

### 3. Fund the bank wallet

Your `BANK_MNEMONIC` wallet needs:
- **testnet ALGO** — ~2 ALGO covers MBR + fees for all 4 agents  
  → [Algorand Testnet Dispenser](https://bank.testnet.algorand.network/)
- **testnet USDC** (ASA `10458941`) — ~2 USDC covers all attests + revokes  
  → Swap on [Tinyman testnet](https://testnet.tinyman.org/) or use a faucet

### 4. Run

```bash
cd agents/
uv run python world.py
```

On first run, four agent wallets are generated and saved to `agents.json`. The bank funds each one. Then all agents run concurrently.

**Re-runs** reuse the same wallets (delete `agents.json` to reset).

## How the x402 payment works

Each agent holds its own Algorand wallet. When an agent calls `POST /attest`:

1. Captre responds `402 Payment Required` with a payment challenge in `X-Payment-Required`
2. The agent's `AlgorandWallet` (which implements the `ClientAvmSigner` protocol) signs an Algorand USDC transfer transaction
3. The signed payment is sent back as `X-Payment-Payload` in the retry request
4. The GoPlausible facilitator verifies and settles the payment
5. Captre writes the attestation box on-chain — the agent's address is permanently recorded as `author`

The `author` field in every on-chain attestation is the **agent's own Algorand address** — every agent is a distinct, identifiable actor.

## One bank, many agents

Rather than manually funding every wallet, `world.py` uses a single `BANK_MNEMONIC` to:
1. Send ALGO to each agent (covers MBR + fee buffer)
2. Opt each agent into the USDC ASA if needed
3. Send USDC to each agent (covers ~4 attests + 1 revoke)

This happens automatically before the simulation starts.
