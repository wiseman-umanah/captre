"""
Force an in-place UpdateApplication on the live contract.

deploy.py skips the update when APP_ID is already set. This script
bypasses that guard and submits an ApplicationUpdate transaction directly,
pushing the newly compiled TEAL (which includes admin_delete_box) onto
the existing app without touching any boxes or changing APP_ID.

No schema change is involved — only a new method is added — so
UpdateApplication is safe and will not be rejected.

Usage:
    uv run python -m captre.contract.scripts.update_contract

Reads from .env:
    ALGOD_URL           — must point at mainnet
    ALGOD_TOKEN         — leave blank for public nodes
    DEPLOYER_MNEMONIC   — must be the contract creator
    APP_ID              — the contract to update (e.g. 3682418169)
"""

import os
from pathlib import Path

from algosdk import transaction
from algosdk.account import address_from_private_key
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from dotenv import load_dotenv

load_dotenv()

ALGOD_URL: str = os.environ["ALGOD_URL"]
ALGOD_TOKEN: str = os.environ.get("ALGOD_TOKEN", "")
DEPLOYER_MNEMONIC: str = os.environ["DEPLOYER_MNEMONIC"]
APP_ID: int = int(os.environ["APP_ID"])

_ARTIFACTS = Path(__file__).parent.parent / "artifacts"


def update() -> None:
    """
    Submit an ApplicationUpdate transaction to push new TEAL onto APP_ID.

    Reads the compiled approval and clear programs from the artifacts
    directory and submits an ``ApplicationUpdateTxn``. The existing
    boxes, APP_ID, and APP_ADDRESS are all unchanged.

    Returns
    -------
    None
        Prints the confirmed transaction ID on success.

    Raises
    ------
    FileNotFoundError
        If the compiled TEAL artifacts are missing. Run the compile
        isolation workaround first.
    RuntimeError
        If the update transaction is rejected.
    """
    approval_path = _ARTIFACTS / "CaptreApp.approval.teal"
    clear_path = _ARTIFACTS / "CaptreApp.clear.teal"

    if not approval_path.exists() or not clear_path.exists():
        raise FileNotFoundError(
            f"Compiled TEAL not found in {_ARTIFACTS}.\n"
            "Run the compile isolation workaround first:\n"
            "  mkdir -p /tmp/captre_compile && "
            "cp src/captre/contract/captre_app.py /tmp/captre_compile/ && "
            "algokit compile python /tmp/captre_compile/captre_app.py "
            "--out-dir /tmp/captre_compile/artifacts --output-arc32 && "
            "cp /tmp/captre_compile/artifacts/* src/captre/contract/artifacts/ && "
            "rm -rf /tmp/captre_compile"
        )

    client = AlgodClient(ALGOD_TOKEN, ALGOD_URL)
    private_key = to_private_key(DEPLOYER_MNEMONIC)
    deployer_address: str = address_from_private_key(private_key)

    # Compile TEAL source to bytecode via algod
    print("[update] Compiling approval program ...")
    approval_src = approval_path.read_text()
    approval_result = client.compile(approval_src)
    approval_b64: str = approval_result["result"]
    import base64
    approval_bytes = base64.b64decode(approval_b64)

    print("[update] Compiling clear program ...")
    clear_src = clear_path.read_text()
    clear_result = client.compile(clear_src)
    clear_bytes = base64.b64decode(clear_result["result"])

    sp = client.suggested_params()
    txn = transaction.ApplicationUpdateTxn(
        sender=deployer_address,
        sp=sp,
        index=APP_ID,
        approval_program=approval_bytes,
        clear_program=clear_bytes,
    )

    signed = txn.sign(private_key)
    tx_id = client.send_transaction(signed)
    print(f"[update] ApplicationUpdate submitted: txid={tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, wait_rounds=10)
    confirmed_round = result.get("confirmed-round", "?")
    print(f"[update] Confirmed in round {confirmed_round}.")
    print(f"[update] APP_ID={APP_ID} now has admin_delete_box.")
    print("[update] Next step: run cleanup_boxes.py")


if __name__ == "__main__":
    update()
