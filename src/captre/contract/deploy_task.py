"""
Deploy (or re-use) the TaskApp smart contract on Algorand.

Usage:
    uv run python -m captre.contract.deploy_task

Reads from .env:
    ALGOD_URL           — e.g. https://mainnet-api.algonode.cloud
    ALGOD_TOKEN         — leave blank for public nodes
    DEPLOYER_MNEMONIC   — 25-word mnemonic for the service/deployer account
    TASK_APP_ID         — if set, skips deployment and reuses this app id

Writes to .env (or prints) after first deploy:
    TASK_APP_ID         — the deployed application id
    TASK_APP_ADDRESS    — the contract account address (must be funded ≥2 ALGO for box MBR)
"""

import json
import os

from algokit_utils import AlgorandClient, OnSchemaBreak, OnUpdate, SigningAccount
from algosdk.mnemonic import to_private_key
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from dotenv import load_dotenv, set_key

load_dotenv()

ALGOD_URL = os.environ["ALGOD_URL"]
ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")
DEPLOYER_MNEMONIC = os.environ["DEPLOYER_MNEMONIC"]
ENV_FILE = ".env"

INDEXER_URL = os.environ.get("INDEXER_URL", "https://mainnet-idx.algonode.cloud")


def get_client() -> AlgorandClient:
    """
    Build an ``AlgorandClient`` from the environment-configured algod and
    indexer URLs.

    Returns
    -------
    AlgorandClient
        A connected algokit-utils client ready for deployment and interaction.
    """
    return AlgorandClient.from_clients(
        AlgodClient(ALGOD_TOKEN, ALGOD_URL),
        IndexerClient("", INDEXER_URL),
    )


def deploy() -> int:
    """
    Deploy the TaskApp contract and return its application ID.

    If ``TASK_APP_ID`` is already set in the environment the existing deployment
    is reused and no new transaction is submitted. Otherwise the contract is
    compiled from the ARC-56 spec in
    ``src/captre/contract/artifacts/TaskApp.arc56.json`` and deployed with
    ``OnSchemaBreak.ReplaceApp`` / ``OnUpdate.ReplaceApp`` policies.

    After a successful first deploy, ``TASK_APP_ID`` and ``TASK_APP_ADDRESS``
    are written back to the ``.env`` file so subsequent runs reuse the same
    application.

    Parameters
    ----------
    (none)

    Returns
    -------
    int
        The Algorand application ID of the deployed (or reused) TaskApp.

    Raises
    ------
    FileNotFoundError
        If the compiled ARC-56 artifact is not found. Run the compile
        isolation workaround first.
    RuntimeError
        If the ``algokit-utils`` deployment call fails.
    """
    existing = os.environ.get("TASK_APP_ID")
    if existing:
        print(f"[deploy_task] Reusing existing TASK_APP_ID={existing}")
        return int(existing)

    client = get_client()
    private_key = to_private_key(DEPLOYER_MNEMONIC)
    deployer = SigningAccount(private_key=private_key)

    spec_path = os.path.join(os.path.dirname(__file__), "artifacts", "TaskApp.arc56.json")
    if not os.path.exists(spec_path):
        raise FileNotFoundError(
            f"Compiled contract not found at {spec_path}.\n"
            "Run the compile isolation workaround (see task_app.py module docstring)."
        )

    with open(spec_path) as f:
        app_spec = json.load(f)

    app_factory = client.client.get_app_factory(
        app_spec=app_spec,
        default_sender=deployer.address,
        default_signer=deployer.signer,
    )

    result, _ = app_factory.deploy(
        on_schema_break=OnSchemaBreak.ReplaceApp,
        on_update=OnUpdate.AppendApp,
    )
    app_id = result.app_id
    print(f"[deploy_task] TaskApp deployed. TASK_APP_ID={app_id}  TASK_APP_ADDRESS={result.app_address}")
    print(f"[deploy_task] IMPORTANT: Fund {result.app_address} with at least 2 ALGO before use.")

    set_key(ENV_FILE, "TASK_APP_ID", str(app_id))
    set_key(ENV_FILE, "TASK_APP_ADDRESS", result.app_address)

    return app_id


if __name__ == "__main__":
    deploy()
