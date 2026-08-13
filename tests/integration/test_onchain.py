"""
Integration tests — live Algorand testnet.

These tests hit the REAL contract (APP_ID from .env) and cost a small amount
of gas per transaction. Run deliberately:

    uv run pytest tests/integration/ -v -s

Requirements:
    - .env must have SERVICE_MNEMONIC, APP_ID, ALGOD_URL set
    - Service account must have enough ALGO for MBR + fees (~0.01 ALGO per test)
    - Each run uses a unique content_hash so tests never collide with each other

Skipped automatically if APP_ID or SERVICE_MNEMONIC is not set.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import pytest

# Skip entire module if env vars are missing (CI without chain access)
pytestmark = pytest.mark.skipif(
    not os.environ.get("APP_ID") or not os.environ.get("SERVICE_MNEMONIC"),
    reason="APP_ID / SERVICE_MNEMONIC not set — skipping integration tests",
)


@pytest.fixture(scope="module")
def chain_client():
    """Shared AlgorandClient + app_client for the module."""
    from dotenv import load_dotenv
    load_dotenv()

    from algokit_utils import AlgorandClient, BoxReference, SigningAccount
    from algokit_utils.applications.app_client import AppClientMethodCallParams
    from algosdk.mnemonic import to_private_key
    from algosdk.v2client.algod import AlgodClient
    from algosdk.v2client.indexer import IndexerClient
    from pathlib import Path

    app_id = int(os.environ["APP_ID"])
    svc = SigningAccount(private_key=to_private_key(os.environ["SERVICE_MNEMONIC"]))

    client = AlgorandClient.from_clients(
        AlgodClient(os.environ.get("ALGOD_TOKEN", ""), os.environ["ALGOD_URL"]),
        IndexerClient("", os.environ.get("INDEXER_URL", "https://testnet-idx.algonode.cloud")),
    )
    spec = json.load(
        open(Path(__file__).parent.parent.parent /
             "src/captre/contract/artifacts/CaptreApp.arc56.json")
    )
    app = client.client.get_app_client_by_id(
        app_spec=spec,
        app_id=app_id,
        default_sender=svc.address,
        default_signer=svc.signer,
    )
    return {"app": app, "app_id": app_id, "svc": svc}


@pytest.fixture
def unique_hash():
    """A fresh content_hash per test — prevents ERR_ALREADY_CLAIMED collisions."""
    return f"sha256:integration-test-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_attest_writes_both_boxes(chain_client, unique_hash):
    """attest() must write attestations box AND id_index box in one call."""
    from algokit_utils import BoxReference
    from algokit_utils.applications.app_client import AppClientMethodCallParams

    app = chain_client["app"]
    app_id = chain_client["app_id"]
    author = chain_client["svc"].address

    attestation_id = str(uuid.uuid4())
    metadata = json.dumps({
        "attestation_id": attestation_id,
        "author": author,
        "content_hash": unique_hash,
        "status": "active",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }).encode()

    ch_b = unique_hash.encode()
    aid_b = attestation_id.encode()

    app.send.call(AppClientMethodCallParams(
        method="attest",
        args=[ch_b, aid_b, author, metadata],
        box_references=[
            BoxReference(app_id=app_id, name=b"a:" + ch_b),
            BoxReference(app_id=app_id, name=b"i:" + aid_b),
        ],
    ))

    # Verify attestations box
    r = app.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[ch_b],
        box_references=[BoxReference(app_id=app_id, name=b"a:" + ch_b)],
    ))
    stored = json.loads(bytes(r.abi_return).decode())
    assert stored["attestation_id"] == attestation_id
    assert stored["content_hash"] == unique_hash
    assert stored["status"] == "active"

    # Verify id_index box
    r2 = app.send.call(AppClientMethodCallParams(
        method="resolve_id",
        args=[aid_b],
        box_references=[BoxReference(app_id=app_id, name=b"i:" + aid_b)],
    ))
    resolved = bytes(r2.abi_return).decode()
    assert resolved == unique_hash


def test_get_attestation_missing_returns_empty(chain_client):
    """get_attestation() on a non-existent key must return empty bytes (not error)."""
    from algokit_utils import BoxReference
    from algokit_utils.applications.app_client import AppClientMethodCallParams

    app = chain_client["app"]
    app_id = chain_client["app_id"]

    no_such = b"sha256:does-not-exist-" + uuid.uuid4().hex.encode()

    r = app.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[no_such],
        box_references=[BoxReference(app_id=app_id, name=b"a:" + no_such)],
    ))
    assert bytes(r.abi_return) == b""


def test_resolve_id_missing_returns_empty(chain_client):
    """resolve_id() on a non-existent UUID must return empty bytes (not error)."""
    from algokit_utils import BoxReference
    from algokit_utils.applications.app_client import AppClientMethodCallParams

    app = chain_client["app"]
    app_id = chain_client["app_id"]

    no_such = str(uuid.uuid4()).encode()

    r = app.send.call(AppClientMethodCallParams(
        method="resolve_id",
        args=[no_such],
        box_references=[BoxReference(app_id=app_id, name=b"i:" + no_such)],
    ))
    assert bytes(r.abi_return) == b""


def test_duplicate_attest_raises_already_claimed(chain_client, unique_hash):
    """Attesting the same content_hash twice must trigger ERR_ALREADY_CLAIMED."""
    from algokit_utils import BoxReference
    from algokit_utils.applications.app_client import AppClientMethodCallParams

    app = chain_client["app"]
    app_id = chain_client["app_id"]
    author = chain_client["svc"].address

    def do_attest():
        aid_b = str(uuid.uuid4()).encode()
        ch_b = unique_hash.encode()
        meta = json.dumps({"attestation_id": aid_b.decode(), "author": author,
                           "content_hash": unique_hash, "status": "active",
                           "created_at": datetime.now(tz=timezone.utc).isoformat()}).encode()
        app.send.call(AppClientMethodCallParams(
            method="attest",
            args=[ch_b, aid_b, author, meta],
            box_references=[
                BoxReference(app_id=app_id, name=b"a:" + ch_b),
                BoxReference(app_id=app_id, name=b"i:" + aid_b),
            ],
        ))

    do_attest()  # first — must succeed

    with pytest.raises(Exception) as exc_info:
        do_attest()  # second — must fail

    full = " ".join(str(e) for e in [
        exc_info.value,
        exc_info.value.__cause__,
        exc_info.value.__context__,
    ] if e)
    assert "ERR_ALREADY_CLAIMED" in full


def test_revoke_updates_box(chain_client, unique_hash):
    """revoke() must overwrite the attestations box with the updated metadata."""
    from algokit_utils import BoxReference
    from algokit_utils.applications.app_client import AppClientMethodCallParams

    app = chain_client["app"]
    app_id = chain_client["app_id"]
    author = chain_client["svc"].address

    attestation_id = str(uuid.uuid4())
    ch_b = unique_hash.encode()
    aid_b = attestation_id.encode()

    meta_active = json.dumps({
        "attestation_id": attestation_id, "author": author,
        "content_hash": unique_hash, "status": "active",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }).encode()

    # Attest first
    app.send.call(AppClientMethodCallParams(
        method="attest",
        args=[ch_b, aid_b, author, meta_active],
        box_references=[
            BoxReference(app_id=app_id, name=b"a:" + ch_b),
            BoxReference(app_id=app_id, name=b"i:" + aid_b),
        ],
    ))

    # Revoke
    meta_revoked = json.dumps({
        "attestation_id": attestation_id, "author": author,
        "content_hash": unique_hash, "status": "revoked",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }).encode()

    app.send.call(AppClientMethodCallParams(
        method="revoke",
        args=[ch_b, author, meta_revoked],
        box_references=[BoxReference(app_id=app_id, name=b"a:" + ch_b)],
    ))

    # Read back — must be revoked
    r = app.send.call(AppClientMethodCallParams(
        method="get_attestation",
        args=[ch_b],
        box_references=[BoxReference(app_id=app_id, name=b"a:" + ch_b)],
    ))
    stored = json.loads(bytes(r.abi_return).decode())
    assert stored["status"] == "revoked"


def test_full_http_cycle(unique_hash):
    """
    Full end-to-end via the write_attestation / verify module layer
    (same code path the live server uses).
    """
    from dotenv import load_dotenv
    load_dotenv()

    from captre.models import AttestRequest, AttestationStatus
    from captre.settlement.write_attestation import (
        read_attestation_from_box,
        resolve_id_from_chain,
        revoke_attestation,
        write_attestation,
    )

    author = os.environ.get(
        "RECEIVER_ADDRESS",
        # fall back to service account address derived from mnemonic
        __import__("algosdk").mnemonic.to_public_key(os.environ["SERVICE_MNEMONIC"]),
    )

    # 1. Attest
    req = AttestRequest(
        content_hash=unique_hash,
        agent_id="integration-test",
        description="full http cycle test",
    )
    attestation = write_attestation(req, payer_address=author, payment_tx_id="test-tx-001")
    assert attestation.content_hash == unique_hash
    assert attestation.author == author
    assert attestation.status == AttestationStatus.active

    # 2. Read back by content_hash
    found = read_attestation_from_box(unique_hash)
    assert found is not None
    assert found.attestation_id == attestation.attestation_id

    # 3. Resolve UUID → content_hash on-chain
    resolved_hash = resolve_id_from_chain(attestation.attestation_id)
    assert resolved_hash == unique_hash

    # 4. Revoke
    revoked = revoke_attestation(
        content_hash=unique_hash,
        payer_address=author,
        existing=found,
        payment_tx_id="test-tx-002",
    )
    assert revoked.status == AttestationStatus.revoked

    # 5. Confirm revoked status is on-chain
    after_revoke = read_attestation_from_box(unique_hash)
    assert after_revoke.status == AttestationStatus.revoked
