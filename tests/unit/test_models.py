"""
Unit tests for Pydantic models — validation, enum coercion, serialisation.
No chain, no HTTP.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from captre.models import (
    Attestation,
    AttestationStatus,
    AttestRequest,
    AttestResponse,
    ErrorResponse,
    OutputType,
    RevokeRequest,
    RevokeResponse,
    VerifyResponse,
)
from tests.conftest import (
    FAKE_ATTESTATION_ID,
    FAKE_AUTHOR,
    FAKE_CONTENT_HASH,
    FAKE_TX_ID,
)

# ---------------------------------------------------------------------------
# AttestRequest
# ---------------------------------------------------------------------------

def test_attest_request_minimal():
    req = AttestRequest(content_hash="sha256:abc")
    assert req.content_hash == "sha256:abc"
    assert req.tags == []
    assert req.extra == {}
    assert req.agent_id is None


def test_attest_request_full():
    req = AttestRequest(
        content_hash="sha256:abc",
        agent_id="agent-1",
        output_type="code",
        description="desc",
        model="gpt-4",
        previous_attestation="sha256:prev",
        tags=["a", "b"],
        extra={"k": "v"},
    )
    assert req.output_type == OutputType.code
    assert req.tags == ["a", "b"]


def test_attest_request_invalid_output_type():
    with pytest.raises(ValidationError):
        AttestRequest(content_hash="sha256:abc", output_type="nonsense")


def test_attest_request_missing_content_hash():
    with pytest.raises(ValidationError):
        AttestRequest()


# ---------------------------------------------------------------------------
# RevokeRequest
# ---------------------------------------------------------------------------

def test_revoke_request_requires_attestation_id():
    with pytest.raises(ValidationError):
        RevokeRequest()

def test_revoke_request_valid():
    r = RevokeRequest(attestation_id=FAKE_ATTESTATION_ID)
    assert r.attestation_id == FAKE_ATTESTATION_ID


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

def test_attestation_default_status():
    a = Attestation(
        attestation_id=FAKE_ATTESTATION_ID,
        author=FAKE_AUTHOR,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        tx_id=FAKE_TX_ID,
        content_hash=FAKE_CONTENT_HASH,
    )
    assert a.status == AttestationStatus.active


def test_attestation_revoked_status():
    a = Attestation(
        attestation_id=FAKE_ATTESTATION_ID,
        author=FAKE_AUTHOR,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        tx_id=FAKE_TX_ID,
        content_hash=FAKE_CONTENT_HASH,
        status="revoked",
    )
    assert a.status == AttestationStatus.revoked


def test_attestation_model_dump_json_roundtrip(fake_attestation):
    """model_dump_json → model_validate must be lossless (this is the box serialisation path)."""
    raw = fake_attestation.model_dump_json()
    recovered = Attestation.model_validate_json(raw)
    assert recovered == fake_attestation


def test_attestation_model_copy_update(fake_attestation):
    """model_copy(update=...) is used by revoke_attestation()."""
    revoked = fake_attestation.model_copy(update={"status": AttestationStatus.revoked})
    assert revoked.status == AttestationStatus.revoked
    assert revoked.attestation_id == fake_attestation.attestation_id
    assert fake_attestation.status == AttestationStatus.active  # original unchanged


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

def test_attest_response_default_message(fake_attestation):
    r = AttestResponse(attestation=fake_attestation)
    assert r.message == "Attestation created successfully"


def test_revoke_response_default_message(fake_attestation):
    r = RevokeResponse(attestation=fake_attestation)
    assert r.message == "Attestation revoked successfully"


def test_verify_response_verified_true(fake_attestation):
    r = VerifyResponse(attestation=fake_attestation)
    assert r.verified is True


def test_error_response_no_existing():
    e = ErrorResponse(error="content_hash already claimed")
    assert e.existing_attestation is None


def test_error_response_model_dump_json_serialisable(fake_attestation):
    """model_dump(mode='json') must produce JSON-safe types — used in HTTPException.detail."""
    import json
    e = ErrorResponse(error="oops", existing_attestation=fake_attestation)
    dumped = e.model_dump(mode="json")
    # must not raise
    encoded = json.dumps(dumped)
    assert "oops" in encoded
