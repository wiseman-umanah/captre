"""
shared/bank.py — Smart bank that tops up agent wallets only when needed.

On every world run, the bank inspects each agent's actual on-chain balance
and only sends what is missing:

  - ALGO: only topped up if spendable balance falls below _ALGO_MIN_BALANCE
  - USDC opt-in: only submitted if the agent hasn't opted in yet
  - USDC: only topped up if balance falls below _USDC_MIN_BALANCE

This means re-runs are cheap — already-funded agents are skipped entirely.
No tokens are wasted on agents that still have enough to operate.
"""

from __future__ import annotations

import time

from algosdk import encoding
from algosdk.transaction import (
    AssetOptInTxn,
    AssetTransferTxn,
    PaymentTxn,
    SuggestedParams,
    wait_for_confirmation,
)
from algosdk.v2client.algod import AlgodClient

from shared.log import log
from shared.wallet import AlgorandWallet

# ── Thresholds — only top up when balance drops below these ──────────────────

# Minimum spendable ALGO an agent must have before bank tops up (microALGO).
# 0.2 ALGO: covers ~200 transaction fees at 0.001 ALGO each.
_ALGO_MIN_BALANCE: int = 200_000

# How much ALGO to send when topping up (microALGO).
# 0.5 ALGO: base MBR (0.1) + ASA opt-in MBR (0.1) + fee buffer (0.3).
_ALGO_TOPUP: int = 500_000

# Minimum USDC an agent must have before bank tops up (base units, 6 decimals).
# $0.15: enough for 3 more attests at $0.05 each.
_USDC_MIN_BALANCE: int = 150_000

# How much USDC to send when topping up (base units).
# $0.50: covers ~10 attests or 5 attest+revoke pairs.
_USDC_TOPUP: int = 500_000


def _algod(algod_url: str, algod_token: str) -> AlgodClient:
    """
    Build an AlgodClient from URL and token.

    Parameters
    ----------
    algod_url : str
        Full URL of the Algod node.
    algod_token : str
        API token (empty string for public nodes).

    Returns
    -------
    AlgodClient
        Ready-to-use Algod client.
    """
    return AlgodClient(algod_token, algod_url)


def _sp(client: AlgodClient) -> SuggestedParams:
    """
    Fetch current suggested transaction parameters from the node.

    Parameters
    ----------
    client : AlgodClient
        Connected Algod client.

    Returns
    -------
    SuggestedParams
        Current round-based transaction parameters.
    """
    return client.suggested_params()


def _send_and_confirm(
    client: AlgodClient,
    signed_txn_b64: str,
    log_agent: str,
    log_msg: str,
) -> str:
    """
    Submit a signed transaction and wait for on-chain confirmation.

    Parameters
    ----------
    client : AlgodClient
        Connected Algod client.
    signed_txn_b64 : str
        Base64 string from ``algosdk.encoding.msgpack_encode``.
        Do NOT pre-decode — ``send_raw_transaction`` expects the b64 string.
    log_agent : str
        Agent name for the log line.
    log_msg : str
        Human-readable description emitted on success.

    Returns
    -------
    str
        Confirmed transaction ID.

    Raises
    ------
    Exception
        If the transaction is rejected or confirmation times out.
    """
    txid = client.send_raw_transaction(signed_txn_b64)
    wait_for_confirmation(client, txid, wait_rounds=4)
    log(log_agent, "FUND", log_msg, detail=f"txid={txid[:12]}…")
    return txid


def _get_balances(
    client: AlgodClient,
    address: str,
    usdc_asset_id: int,
) -> tuple[int, int, bool]:
    """
    Read an account's ALGO balance, USDC balance, and USDC opt-in status.

    Parameters
    ----------
    client : AlgodClient
        Connected Algod client.
    address : str
        Algorand address to inspect.
    usdc_asset_id : int
        ASA ID of the USDC token.

    Returns
    -------
    tuple[int, int, bool]
        ``(algo_microalgos, usdc_base_units, is_opted_in)``
        where ``algo_microalgos`` is the *spendable* balance (amount minus
        min-balance) and ``usdc_base_units`` is the raw ASA holding.
        ``is_opted_in`` is True if the account holds the ASA at any balance.
    """
    try:
        info = client.account_info(address)
    except Exception:  # noqa: BLE001
        # Account doesn't exist on-chain yet (never received ALGO)
        return 0, 0, False

    # Spendable ALGO = total amount minus the protocol minimum balance
    algo = max(0, info.get("amount", 0) - info.get("min-balance", 100_000))

    usdc = 0
    opted_in = False
    for asset in info.get("assets", []):
        if asset["asset-id"] == usdc_asset_id:
            opted_in = True
            usdc = asset.get("amount", 0)
            break

    return algo, usdc, opted_in


def fund_agents(
    bank: AlgorandWallet,
    agents: list[AlgorandWallet],
    usdc_asset_id: int,
    algod_url: str,
    algod_token: str = "",
    algo_min: int = _ALGO_MIN_BALANCE,
    algo_topup: int = _ALGO_TOPUP,
    usdc_min: int = _USDC_MIN_BALANCE,
    usdc_topup: int = _USDC_TOPUP,
) -> None:
    """
    Top up each agent wallet only where its balance is below the minimum.

    For each agent:
      1. Read on-chain ALGO, USDC, and opt-in state in one call.
      2. Send ALGO only if spendable balance < ``algo_min``.
      3. Submit USDC opt-in only if not yet opted in (waits for ALGO first).
      4. Send USDC only if USDC balance < ``usdc_min``.

    Agents that are already sufficiently funded are logged and skipped —
    no transactions are submitted for them.

    Parameters
    ----------
    bank : AlgorandWallet
        The funded bank wallet that signs all outgoing transactions.
    agents : list[AlgorandWallet]
        All agent wallets to inspect and top up as needed.
    usdc_asset_id : int
        ASA ID of the USDC token (10458941 on testnet, 31566704 on mainnet).
    algod_url : str
        Algod node URL.
    algod_token : str
        Algod API token (empty for public nodes).
    algo_min : int
        Minimum spendable microALGO before a top-up is triggered.
    algo_topup : int
        microALGO to send when topping up.
    usdc_min : int
        Minimum USDC base units before a top-up is triggered.
    usdc_topup : int
        USDC base units to send when topping up.

    Raises
    ------
    RuntimeError
        If the bank account has insufficient balance to cover a required top-up.
    """
    client = _algod(algod_url, algod_token)
    log("BANK", "INFO", f"Checking {len(agents)} agent wallet(s) — topping up only where needed.")

    # ── Ensure bank is opted into USDC ───────────────────────────────────────
    _, _, bank_opted_in = _get_balances(client, bank.address, usdc_asset_id)
    if not bank_opted_in:
        log("BANK", "INFO", "Bank not opted into USDC — opting in now…")
        opt_txn = AssetOptInTxn(sender=bank.address, sp=_sp(client), index=usdc_asset_id)
        _send_and_confirm(
            client,
            encoding.msgpack_encode(opt_txn.sign(bank._private_key)),
            "BANK",
            f"Bank opted-in to USDC ASA {usdc_asset_id}",
        )
        time.sleep(1)

    # ── Per-agent smart top-up ────────────────────────────────────────────────
    for agent in agents:
        algo, usdc, opted_in = _get_balances(client, agent.address, usdc_asset_id)
        name = agent.address[:12] + "…"
        needs_algo = algo < algo_min
        needs_optin = not opted_in
        needs_usdc = usdc < usdc_min

        if not needs_algo and not needs_optin and not needs_usdc:
            log("BANK", "INFO", f"  {name}  already funded  (ALGO={algo/1e6:.3f}  USDC={usdc/1e6:.2f}) — skipping")
            continue

        log("BANK", "INFO",
            f"  {name}  ALGO={algo/1e6:.3f}  USDC={usdc/1e6:.2f}  opted_in={opted_in}  →  "
            f"{'ALGO ' if needs_algo else ''}"
            f"{'OPT-IN ' if needs_optin else ''}"
            f"{'USDC' if needs_usdc else ''}".strip()
        )

        # ── 1. Top up ALGO if needed ──────────────────────────────────────
        if needs_algo:
            txn = PaymentTxn(sender=bank.address, sp=_sp(client), receiver=agent.address, amt=algo_topup)
            _send_and_confirm(
                client,
                encoding.msgpack_encode(txn.sign(bank._private_key)),
                "BANK",
                f"→ {name} +{algo_topup / 1_000_000:.3f} ALGO",
            )
            time.sleep(4)  # wait for ALGO to land before submitting agent-signed opt-in

        # ── 2. Opt-in to USDC if needed ───────────────────────────────────
        if needs_optin:
            opt_txn = AssetOptInTxn(sender=agent.address, sp=_sp(client), index=usdc_asset_id)
            _send_and_confirm(
                client,
                encoding.msgpack_encode(opt_txn.sign(agent._private_key)),
                "BANK",
                f"  {name} opted-in to USDC ASA {usdc_asset_id}",
            )
            time.sleep(1)

        # ── 3. Top up USDC if needed ──────────────────────────────────────
        if needs_usdc:
            txn = AssetTransferTxn(
                sender=bank.address, sp=_sp(client),
                receiver=agent.address, amt=usdc_topup, index=usdc_asset_id,
            )
            _send_and_confirm(
                client,
                encoding.msgpack_encode(txn.sign(bank._private_key)),
                "BANK",
                f"→ {name} +{usdc_topup / 1_000_000:.2f} USDC",
            )
            time.sleep(1)

    log("BANK", "SUCCESS", "All agents checked and ready.")
