"""
Unit tests for GET /verify and GET /attestation/:id endpoints.

read_attestation_from_box and resolve_id_from_chain are mocked.
No chain, no USDC.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FAKE_ATTESTATION_ID, FAKE_CONTENT_HASH


@pytest.fixture
def client():
    from captre import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------

def test_verify_found(client, fake_attestation):
    with patch(
        "captre.api.verify.read_attestation_from_box",
        return_value=fake_attestation,
    ):
        resp = client.get("/verify", params={"content_hash": FAKE_CONTENT_HASH})

    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is True
    assert body["attestation"]["content_hash"] == FAKE_CONTENT_HASH


def test_verify_not_found(client):
    with patch(
        "captre.api.verify.read_attestation_from_box",
        return_value=None,
    ):
        resp = client.get("/verify", params={"content_hash": "sha256:unknown"})

    assert resp.status_code == 404


def test_verify_missing_param(client):
    resp = client.get("/verify")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /attestation/:id  — UUID path (resolve_id_from_chain finds content_hash)
# ---------------------------------------------------------------------------

def test_get_attestation_by_uuid(client, fake_attestation):
    with (
        patch(
            "captre.api.verify.resolve_id_from_chain",
            return_value=FAKE_CONTENT_HASH,
        ),
        patch(
            "captre.api.verify.read_attestation_from_box",
            return_value=fake_attestation,
        ),
    ):
        resp = client.get(f"/attestation/{FAKE_ATTESTATION_ID}")

    assert resp.status_code == 200
    assert resp.json()["attestation"]["attestation_id"] == FAKE_ATTESTATION_ID


def test_get_attestation_by_content_hash_directly(client, fake_attestation):
    """
    When the param is a content_hash (not a UUID), resolve_id_from_chain returns
    None, and the fallback direct box read succeeds.
    """
    with (
        patch(
            "captre.api.verify.resolve_id_from_chain",
            return_value=None,
        ),
        patch(
            "captre.api.verify.read_attestation_from_box",
            return_value=fake_attestation,
        ),
    ):
        resp = client.get(f"/attestation/{FAKE_CONTENT_HASH}")

    assert resp.status_code == 200


def test_get_attestation_not_found(client):
    with (
        patch("captre.api.verify.resolve_id_from_chain", return_value=None),
        patch("captre.api.verify.read_attestation_from_box", return_value=None),
    ):
        resp = client.get("/attestation/totally-unknown-id")

    assert resp.status_code == 404


def test_get_attestation_uuid_resolves_but_box_missing(client):
    """
    resolve_id_from_chain finds a content_hash but the box read returns None
    (chain inconsistency). Falls through to direct lookup — also None → 404.
    """
    with (
        patch(
            "captre.api.verify.resolve_id_from_chain",
            return_value=FAKE_CONTENT_HASH,
        ),
        patch("captre.api.verify.read_attestation_from_box", return_value=None),
    ):
        resp = client.get(f"/attestation/{FAKE_ATTESTATION_ID}")

    assert resp.status_code == 404
