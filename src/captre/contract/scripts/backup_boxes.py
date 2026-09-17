"""
Step 1 of MBR reclaim: back up all attestation box contents to a JSON file.

Run BEFORE deleting any boxes. Reads all 14 boxes from the live mainnet
contract, decodes the attestation records, and writes them to
``box_backup_<APP_ID>.json`` in the project root.

Usage:
    uv run python -m captre.contract.scripts.backup_boxes

Reads from .env:
    ALGOD_URL           — must point at mainnet
    ALGOD_TOKEN         — leave blank for public nodes
    APP_ID              — the contract to back up (e.g. 3682418169)
"""

import base64
import json
import os
import sys
from pathlib import Path

from algosdk.v2client.algod import AlgodClient
from dotenv import load_dotenv

load_dotenv()

ALGOD_URL: str = os.environ["ALGOD_URL"]
ALGOD_TOKEN: str = os.environ.get("ALGOD_TOKEN", "")
APP_ID: int = int(os.environ["APP_ID"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


def _decode_box_name(name_dict: dict) -> bytes:
    """
    Convert the algod box name dict (``{0: int, 1: int, ...}``) to bytes.

    Parameters
    ----------
    name_dict : dict
        The raw box name object returned by ``application_boxes``.

    Returns
    -------
    bytes
        The box name as a raw byte string.
    """
    return bytes(name_dict[str(i)] if str(i) in name_dict else name_dict[i]
                 for i in range(len(name_dict)))


def backup() -> None:
    """
    Fetch all boxes from the live contract and write a backup JSON file.

    Enumerates every box on ``APP_ID``, reads its value, and writes a
    list of records to ``box_backup_<APP_ID>.json``. Attestation boxes
    (``a:`` prefix) are decoded to ``Attestation`` JSON. Id_index boxes
    (``i:`` prefix) are stored as raw UTF-8 strings.

    Returns
    -------
    None
        Writes the backup file and prints a summary.

    Raises
    ------
    SystemExit
        If the backup file already exists (safety guard — won't overwrite).
    """
    client = AlgodClient(ALGOD_TOKEN, ALGOD_URL)

    out_path = _PROJECT_ROOT / f"box_backup_{APP_ID}.json"
    if out_path.exists():
        print(f"[backup] ABORT: {out_path} already exists. Delete it first if you want to re-run.")
        sys.exit(1)

    print(f"[backup] Reading boxes from APP_ID={APP_ID} ...")
    result = client.application_boxes(APP_ID)
    boxes_raw = result.get("boxes", [])
    print(f"[backup] Found {len(boxes_raw)} boxes total.")

    records = []
    for box_meta in boxes_raw:
        # algod SDK returns box names as base64-encoded strings
        raw_name: bytes = base64.b64decode(box_meta["name"])
        # Encode name as base64 for safe JSON storage
        name_b64: str = box_meta["name"]
        prefix = chr(raw_name[0]) + chr(raw_name[1])  # "a:" or "i:"

        # Fetch box value
        box_info = client.application_box_by_name(APP_ID, raw_name)
        value_b64: str = box_info.get("value", "")
        value_bytes = base64.b64decode(value_b64) if value_b64 else b""

        record: dict = {
            "box_name_b64": name_b64,
            "prefix": prefix,
            "value_b64": value_b64,
        }

        # Decode attestation JSON for human readability
        if prefix == "a:" and value_bytes:
            try:
                record["attestation"] = json.loads(value_bytes.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                record["attestation_decode_error"] = str(exc)
        elif prefix == "i:" and value_bytes:
            try:
                record["content_hash_str"] = value_bytes.decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                record["content_hash_decode_error"] = str(exc)

        records.append(record)
        print(f"  [{prefix}] backed up {len(value_bytes)} bytes")

    out_path.write_text(json.dumps(records, indent=2))
    print(f"\n[backup] Done. Written to: {out_path}")
    print(f"[backup] {sum(1 for r in records if r['prefix'] == 'a:')} attestations backed up.")
    print("[backup] Review the file before proceeding to cleanup.")


if __name__ == "__main__":
    backup()
