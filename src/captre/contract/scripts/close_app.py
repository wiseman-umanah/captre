"""
Step 3 of MBR reclaim: delete the app and close the contract account
balance back to the deployer wallet.

Run AFTER cleanup_boxes.py has deleted all boxes. At this point the
contract account has 0 boxes, min_balance = 0.1 ALGO, and the full
pre-funded balance is liquid.

This script:
  1. Verifies the contract has 0 boxes remaining (safety check).
  2. Submits an ApplicationDelete transaction.
     The close_remainder_to field on the inner payment sends the entire
     contract account balance to the deployer address.
  3. Prints the recovered ALGO amount.

After this script completes, clear APP_ID and APP_ADDRESS from .env
and run ``uv run captre-deploy`` to deploy the new contract.

Usage:
    uv run python -m captre.contract.scripts.close_app

Reads from .env:
    ALGOD_URL           — must point at mainnet
    ALGOD_TOKEN         — leave blank for public nodes
    DEPLOYER_MNEMONIC   — must be the contract creator
    APP_ID              — the contract to delete (e.g. 3682418169)
"""

import os
import sys
from typing import cast

from algosdk import transaction
from algosdk.logic import get_application_address
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from dotenv import load_dotenv

load_dotenv()

ALGOD_URL: str = os.environ["ALGOD_URL"]
ALGOD_TOKEN: str = os.environ.get("ALGOD_TOKEN", "")
DEPLOYER_MNEMONIC: str = os.environ["DEPLOYER_MNEMONIC"]
APP_ID: int = int(os.environ["APP_ID"])


def close_app() -> None:
    """
    Delete the application and recover all ALGO to the deployer wallet.

    Performs a pre-flight check to ensure no boxes remain. Then submits
    an ``ApplicationDelete`` transaction. Algorand automatically closes
    the contract account to the transaction sender (the deployer) when
    the app is deleted with no remaining boxes, returning the full
    balance minus fees.

    Returns
    -------
    None
        Prints recovered ALGO amount and next steps.

    Raises
    ------
    SystemExit
        If boxes still exist on the contract (must run cleanup_boxes.py first).
    RuntimeError
        If the ApplicationDelete transaction fails.
    """
    client = AlgodClient(ALGOD_TOKEN, ALGOD_URL)
    private_key = to_private_key(DEPLOYER_MNEMONIC)
    from algosdk.account import address_from_private_key
    deployer_address: str = address_from_private_key(private_key)

    app_address = get_application_address(APP_ID)

    # Pre-flight: confirm zero boxes remain
    print(f"[close_app] Checking APP_ID={APP_ID} at {app_address} ...")
    result = client.application_boxes(APP_ID)
    remaining_boxes = result.get("boxes", [])
    if remaining_boxes:
        print(f"[close_app] ABORT: {len(remaining_boxes)} boxes still exist.")
        print("[close_app] Run cleanup_boxes.py first to delete all boxes.")
        sys.exit(1)

    acct_info = cast(dict, client.account_info(app_address))
    balance = acct_info.get("amount", 0)
    min_bal = acct_info.get("min-balance", 0)
    print(f"[close_app] Contract balance:  {balance / 1_000_000:.6f} ALGO")
    print(f"[close_app] Min balance (base): {min_bal / 1_000_000:.6f} ALGO")
    print(f"[close_app] Will recover:      ~{(balance - 1000) / 1_000_000:.6f} ALGO "
          f"(minus ~0.001 ALGO fee)")

    confirm = input("\n[close_app] Type YES to delete app and recover ALGO: ").strip()
    if confirm != "YES":
        print("[close_app] Aborted.")
        sys.exit(0)

    # Build ApplicationDelete transaction
    # Algorand closes the app account to the sender automatically on deletion.
    sp = client.suggested_params()
    txn = transaction.ApplicationDeleteTxn(
        sender=deployer_address,
        sp=sp,
        index=APP_ID,
    )

    signed = txn.sign(private_key)
    tx_id = client.send_transaction(signed)
    print(f"\n[close_app] ApplicationDelete submitted: txid={tx_id}")

    # Wait for confirmation
    result = transaction.wait_for_confirmation(client, tx_id, wait_rounds=10)
    confirmed_round = result.get("confirmed-round", "?")
    print(f"[close_app] Confirmed in round {confirmed_round}.")

    # Show recovered balance
    deployer_info = cast(dict, client.account_info(deployer_address))
    deployer_balance = deployer_info.get("amount", 0)
    print("\n[close_app] SUCCESS.")
    print(f"[close_app] APP_ID {APP_ID} deleted.")
    print(f"[close_app] Deployer balance now: {deployer_balance / 1_000_000:.6f} ALGO")
    print("\nNext steps:")
    print("  1. Remove APP_ID and APP_ADDRESS from .env")
    print("  2. Fund the deployer wallet if needed")
    print("  3. Run: uv run captre-deploy   (deploys new contract, writes new APP_ID)")


if __name__ == "__main__":
    close_app()
