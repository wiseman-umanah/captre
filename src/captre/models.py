"""
Pydantic schemas for Captre request bodies, stored records, and API responses.

All field names match the PRD §5 specification exactly. Do not rename them —
the same names are used as box-storage JSON keys on-chain.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OutputType(str, Enum):
    """Enumeration of supported content output types for an attestation."""

    research = "research"
    file = "file"
    decision = "decision"
    code = "code"
    report = "report"
    other = "other"


class AttestationStatus(str, Enum):
    """Lifecycle status of an attestation stored on-chain."""

    active = "active"
    revoked = "revoked"


# --- Request bodies ---

class AttestRequest(BaseModel):
    """
    Body of a POST /attest request.

    Attributes
    ----------
    content_hash : str
        SHA-256 (or equivalent) hash of the content being attested,
        e.g. ``sha256:abc123...``. Must be globally unique — once claimed
        it cannot be re-attested even after revocation.
    agent_id : str or None
        Optional identifier for the agent or system that produced the content.
    output_type : OutputType or None
        Category of the attested content (research, file, decision, …).
    description : str or None
        Human-readable description of what is being attested.
    model : str or None
        AI model name or version that produced the content, if applicable.
    previous_attestation : str or None
        ``attestation_id`` or ``content_hash`` of a prior attestation this
        one supersedes or references.
    tags : list[str]
        Free-form tags for discovery and filtering. Defaults to ``[]``.
    extra : dict[str, Any]
        Arbitrary key/value metadata. Defaults to ``{}``.
    """

    content_hash: str = Field(..., description="SHA-256 hash of the content, e.g. sha256:abc123...")
    agent_id: str | None = None
    output_type: OutputType | None = None
    description: str | None = None
    model: str | None = None
    previous_attestation: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class RevokeRequest(BaseModel):
    """
    Body of a POST /revoke request.

    Attributes
    ----------
    attestation_id : str
        UUID ``attestation_id`` **or** raw ``content_hash`` of the attestation
        to revoke. The endpoint resolves UUIDs via the on-chain ``id_index``
        BoxMap before proceeding.
    """

    attestation_id: str


# --- Stored record (written to box / returned in responses) ---

class Attestation(BaseModel):
    """
    Full attestation record — written to Algorand box storage as JSON and
    returned verbatim in API responses.

    Attributes
    ----------
    attestation_id : str
        Server-generated UUID assigned at attest time.
    author : str
        Algorand address of the x402 payment payer. **Never** sourced from
        ``Txn.sender()`` — that is always the backend service account.
    created_at : datetime
        UTC timestamp of when the attestation was written on-chain.
    tx_id : str
        Payment group ID from the x402 settlement (used as a stable reference).
    status : AttestationStatus
        ``active`` after creation; ``revoked`` after a successful /revoke call.
    content_hash : str
        The hash being attested (client-supplied, unique constraint enforced on-chain).
    agent_id : str or None
        Optional agent identifier forwarded from the request.
    output_type : OutputType or None
        Content category forwarded from the request.
    description : str or None
        Human-readable description forwarded from the request.
    model : str or None
        AI model identifier forwarded from the request.
    previous_attestation : str or None
        Reference to a prior attestation forwarded from the request.
    tags : list[str]
        Tags forwarded from the request.
    extra : dict[str, Any]
        Arbitrary metadata forwarded from the request.
    """

    # server-controlled
    attestation_id: str
    author: str          # Algorand address from x402 payer — never from Txn.sender()
    created_at: datetime
    tx_id: str
    status: AttestationStatus = AttestationStatus.active

    # client-supplied
    content_hash: str
    agent_id: str | None = None
    output_type: OutputType | None = None
    description: str | None = None
    model: str | None = None
    previous_attestation: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


# --- API responses ---

class AttestResponse(BaseModel):
    """
    Response body for a successful POST /attest.

    Attributes
    ----------
    attestation : Attestation
        The newly created attestation record.
    message : str
        Human-readable confirmation. Defaults to
        ``"Attestation created successfully"``.
    """

    attestation: Attestation
    message: str = "Attestation created successfully"


class RevokeResponse(BaseModel):
    """
    Response body for a successful POST /revoke.

    Attributes
    ----------
    attestation : Attestation
        The updated attestation record with ``status="revoked"``.
    message : str
        Human-readable confirmation. Defaults to
        ``"Attestation revoked successfully"``.
    """

    attestation: Attestation
    message: str = "Attestation revoked successfully"


class VerifyResponse(BaseModel):
    """
    Response body for GET /verify and GET /attestation/:id.

    Attributes
    ----------
    attestation : Attestation
        The attestation record read from on-chain box storage.
    verified : bool
        Always ``True`` when the response is returned (404 is raised otherwise).
    """

    attestation: Attestation
    verified: bool = True


class ErrorResponse(BaseModel):
    """
    Response body for 4xx error responses (e.g. 409 duplicate claim).

    Attributes
    ----------
    error : str
        Short machine-readable error description.
    existing_attestation : Attestation or None
        Populated for 409 responses so the caller can inspect the existing
        record. ``None`` for all other error types.
    """

    error: str
    existing_attestation: Attestation | None = None
