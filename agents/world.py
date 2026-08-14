"""
world.py — The Captre Agent World Orchestrator.

Entry point: uv run python world.py

What happens:
  1. Loads one BANK_MNEMONIC from .env.
  2. Generates four fresh agent wallets (or loads from agents.json if present).
  3. Bank funds all agent wallets with ALGO + testnet USDC.
  4. Runs all four agents CONCURRENTLY in threads (researcher, coder, auditor, critic).
  5. The auditor waits a few seconds before verifying so others can land on-chain.
  6. Terminal output is a colourised real-time log — each agent has its own colour.

Wallets are persisted to agents.json so re-running reuses the same addresses
(saves funding costs on repeated demos). Delete agents.json to reset.

Usage:
  cd agents/
  cp .env.example .env          # fill in BANK_MNEMONIC + node URLs
  uv run python world.py

Prerequisites:
  - BANK_MNEMONIC wallet must hold testnet ALGO and testnet USDC (ASA 10458941).
  - Captre server must be running and reachable at CAPTRE_BASE_URL.
  - AlgoKit not required here — this is pure HTTP + Algorand SDK.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from agents.auditor import AuditorAgent
from agents.coder import CoderAgent
from agents.critic import CriticAgent
from agents.researcher import ResearcherAgent
from dotenv import load_dotenv
from shared.bank import fund_agents
from shared.log import banner, log
from shared.wallet import AlgorandWallet

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
_BANK_MNEMONIC: str = os.environ["BANK_MNEMONIC"]
_ALGOD_URL: str = os.environ.get("ALGOD_URL", "https://testnet-api.algonode.cloud")
_ALGOD_TOKEN: str = os.environ.get("ALGOD_TOKEN", "")
_USDC_ASSET_ID: int = int(os.environ.get("USDC_ASSET_ID", "10458941"))
_AGENTS_FILE = Path(__file__).parent / "agents.json"

# ── Agent names for wallet persistence ───────────────────────────────────────
_AGENT_NAMES = ["researcher", "coder", "auditor", "critic"]


def _load_or_generate_wallets() -> dict[str, AlgorandWallet]:
    """
    Load agent wallets from agents.json or generate fresh ones.

    Returns
    -------
    dict[str, AlgorandWallet]
        Mapping of agent name → wallet. Also persists new wallets to agents.json.
    """
    if _AGENTS_FILE.exists():
        log("BANK", "INFO", f"Loading agent wallets from {_AGENTS_FILE.name}")
        data: dict[str, str] = json.loads(_AGENTS_FILE.read_text())
        wallets = {name: AlgorandWallet(phrase) for name, phrase in data.items()}
        for name, w in wallets.items():
            log("BANK", "INFO", f"  {name:<12} → {w.address[:20]}…")
        return wallets

    log("BANK", "INFO", "Generating fresh agent wallets…")
    wallets: dict[str, AlgorandWallet] = {}
    data: dict[str, str] = {}
    for name in _AGENT_NAMES:
        w = AlgorandWallet.generate()
        wallets[name] = w
        data[name] = w.mnemonic_phrase
        log("BANK", "INFO", f"  {name:<12} → {w.address[:20]}…")

    _AGENTS_FILE.write_text(json.dumps(data, indent=2))
    log("BANK", "SUCCESS", f"Wallets saved to {_AGENTS_FILE.name} — re-runs will reuse them.")
    return wallets


def _run_agent(agent: Any, registry: dict[str, list[dict[str, Any]]]) -> None:
    """
    Thread target: run a single agent's lifecycle and catch top-level errors.

    Parameters
    ----------
    agent : Any
        An agent instance with a .run(registry) method.
    registry : dict[str, list[dict]]
        Shared registry for inter-agent data sharing.
    """
    try:
        agent.run(registry)
    except Exception as exc:  # noqa: BLE001
        log(agent.name, "ERROR", f"Uncaught exception: {exc}")


def main() -> None:
    """
    Run the full agent world simulation.

    Validates environment, funds wallets, then fires all agents concurrently.
    Blocks until all threads complete and prints a final summary.
    """
    banner("CAPTRE AGENT WORLD — starting up")

    # ── Validate env ────────────────────────────────────────────────────
    missing = [k for k in ("BANK_MNEMONIC", "CAPTRE_BASE_URL") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing required env vars: {', '.join(missing)}")
        print("       Copy .env.example → .env and fill them in.")
        sys.exit(1)

    # ── Load / generate wallets ─────────────────────────────────────────
    banner("BANK — wallet setup")
    bank = AlgorandWallet(_BANK_MNEMONIC)
    log("BANK", "INFO", f"Bank address: {bank.address}")
    wallets = _load_or_generate_wallets()

    # ── Fund agents ─────────────────────────────────────────────────────
    banner("BANK — funding agents")
    fund_agents(
        bank=bank,
        agents=list(wallets.values()),
        usdc_asset_id=_USDC_ASSET_ID,
        algod_url=_ALGOD_URL,
        algod_token=_ALGOD_TOKEN,
    )

    # ── Build agent instances ───────────────────────────────────────────
    researcher = ResearcherAgent(wallets["researcher"])
    coder = CoderAgent(wallets["coder"])
    auditor = AuditorAgent(wallets["auditor"])
    critic = CriticAgent(wallets["critic"])

    # ── Shared registry for inter-agent data ────────────────────────────
    # Researcher and coder populate it; auditor and critic read from it.
    registry: dict[str, list[dict[str, Any]]] = {}

    # ── Launch all agents concurrently ──────────────────────────────────
    banner("AGENT WORLD — simulation running")
    threads = [
        threading.Thread(target=_run_agent, args=(researcher, registry), name="researcher", daemon=True),
        threading.Thread(target=_run_agent, args=(coder, registry), name="coder", daemon=True),
        threading.Thread(target=_run_agent, args=(auditor, registry), name="auditor", daemon=True),
        threading.Thread(target=_run_agent, args=(critic, registry), name="critic", daemon=True),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # ── Final summary ────────────────────────────────────────────────────
    banner("SIMULATION COMPLETE — final registry state")
    total = 0
    for agent_name, records in registry.items():
        for r in records:
            status = r.get("status", "?")
            att_id = r.get("attestation_id", "")[:8]
            content_hash = r.get("content_hash", "")[:30]
            log(
                agent_name.upper(), "INFO",
                f"[{status:<7}] {att_id}…  {content_hash}…",
            )
            total += 1
    banner(f"Done — {total} attestation(s) written to Captre")


if __name__ == "__main__":
    main()
