"""
Step 2 of MBR reclaim: delete all boxes one by one, releasing MBR back
to the contract account.

Run AFTER backup_boxes.py and AFTER deploying the updated contract
(with admin_delete_box) via ``uv run captre-deploy`` with APP_ID still set.

Each box deletion releases its locked MBR back to the contract account.
After all 14 boxes are gone the contract account balance becomes fully
liquid (min_balance drops to 0.1 ALGO — the bare account minimum).

Usage:
    uv run python -m captre.contract.scripts.cleanup_boxes

Reads from .env:
    ALGOD_URL           — must point at mainnet
    ALGOD_TOKEN         — leave blank for public nodes
    DEPLOYER_MNEMONIC   — must be the contract creator (admin_delete_box checks this)
    APP_ID              — the contract to clean up (e.g. 3682418169)
"""

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import cast

from algokit_utils import AlgorandClient, BoxReference, SigningAccount
from algokit_utils.applications.app_client import AppClientMethodCallParams
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from dotenv import load_dotenv

load_dotenv()

ALGOD_URL: str = os.environ["ALGOD_URL"]
ALGOD_TOKEN: str = os.environ.get("ALGOD_TOKEN", "")
DEPLOYER_MNEMONIC: str = os.environ["DEPLOYER_MNEMONIC"]
APP_ID: int = int(os.environ["APP_ID"])
INDEXER_URL: str = os.environ.get("INDEXER_URL", "https://mainnet-idx.algonode.cloud")

_ARC56_SPEC = json.loads(
    (Path(__file__).parent.parent / "artifacts" / "CaptreApp.arc56.json").read_text()
)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


def _require_backup() -> None:
    """
    Abort if the backup file does not exist — safety guard.

    Raises
    ------
    SystemExit
        If ``box_backup_<APP_ID>.json`` is not found in the project root.
    """
    backup_path = _PROJECT_ROOT / f"box_backup_{APP_ID}.json"
    if not backup_path.exists():
        print(f"[cleanup] ABORT: backup file not found at {backup_path}")
        print("[cleanup] Run backup_boxes.py first.")
        sys.exit(1)
    print(f"[cleanup] Backup confirmed at {backup_path} — proceeding.")


def cleanup() -> None:
    """
    Delete every box on the contract, releasing all locked MBR.

    Enumerates all boxes via ``application_boxes``, then calls
    ``admin_delete_box`` for each one. Attestation boxes (``a:`` prefix)
    and id_index boxes (``i:`` prefix) are handled correctly via the
    ``is_attestation`` flag.

    A short sleep between transactions avoids node rate-limiting.
    Prints a running total of ALGO unlocked as it proceeds.

    Returns
    -------
    None
        All boxes deleted; prints final summary.

    Raises
    ------
    SystemExit
        If the backup file is missing (safety guard).
    RuntimeError
        If any individual box deletion fails.
    """
    _require_backup()

    algod_client = AlgodClient(ALGOD_TOKEN, ALGOD_URL)
    algorand_client = AlgorandClient.from_clients(
        algod_client,
        IndexerClient("", INDEXER_URL),
    )
    private_key = to_private_key(DEPLOYER_MNEMONIC)
    deployer = SigningAccount(private_key=private_key)

    app_client = algorand_client.client.get_app_client_by_id(
        app_spec=_ARC56_SPEC,
        app_id=APP_ID,
        default_sender=deployer.address,
        default_signer=deployer.signer,
    )

    print(f"[cleanup] Fetching all boxes from APP_ID={APP_ID} ...")
    result = algod_client.application_boxes(APP_ID)
    boxes_raw = result.get("boxes", [])
    total = len(boxes_raw)
    print(f"[cleanup] {total} boxes found. Starting deletion...\n")

    app_address = _get_app_address(APP_ID)
    acct_info = cast(dict, algod_client.account_info(app_address))
    balance_before = acct_info.get("amount", 0)
    min_bal_before = acct_info.get("min-balance", 0)
    print(f"[cleanup] Contract balance: {balance_before / 1_000_000:.6f} ALGO")
    print(f"[cleanup] MBR locked:       {min_bal_before / 1_000_000:.6f} ALGO\n")

    deleted = 0
    for box_meta in boxes_raw:
        # algod SDK returns box names as base64-encoded strings
        raw_name: bytes = base64.b64decode(box_meta["name"])
        prefix = raw_name[:2]          # b"a:" or b"i:"
        box_key = raw_name[2:]         # key without prefix
        is_attestation = (prefix == b"a:")

        label = "attestation" if is_attestation else "id_index"
        print(f"  Deleting {label} box ({len(raw_name)} bytes key)...", end=" ")

        try:
            app_client.send.call(AppClientMethodCallParams(
                method="admin_delete_box",
                args=[box_key, is_attestation],
                box_references=[
                    BoxReference(app_id=APP_ID, name=raw_name),
                ],
            ))
            deleted += 1
            print(f"OK  ({deleted}/{total})")
        except Exception as exc:
            print(f"FAILED\n[cleanup] Error on box {raw_name.hex()}: {exc}")
            raise RuntimeError(f"Box deletion failed: {exc}") from exc

        time.sleep(0.3)   # avoid rate-limit on public nodes

    print(f"\n[cleanup] All {deleted} boxes deleted.")
    print("[cleanup] MBR released back to contract account.")
    print("[cleanup] Next step: run close_app.py to delete the app and recover ALGO.")


def _get_app_address(app_id: int) -> str:
    """
    Resolve the contract account address for a given application ID.

    Parameters
    ----------
    app_id : int
        The Algorand application ID.

    Returns
    -------
    str
        The Algorand address of the contract account.
    """
    from algosdk.logic import get_application_address
    return get_application_address(app_id)


if __name__ == "__main__":
    cleanup()
