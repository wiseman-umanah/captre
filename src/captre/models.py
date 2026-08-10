from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OutputType(str, Enum):
    research = "research"
    file = "file"
    decision = "decision"
    code = "code"
    report = "report"
    other = "other"


class AttestationStatus(str, Enum):
    active = "active"
    revoked = "revoked"


# --- Request bodies ---

class AttestRequest(BaseModel):
    content_hash: str = Field(..., description="SHA-256 hash of the content, e.g. sha256:abc123...")
    agent_id: str | None = None
    output_type: OutputType | None = None
    description: str | None = None
    model: str | None = None
    previous_attestation: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class RevokeRequest(BaseModel):
    attestation_id: str


# --- Stored record (written to box / returned in responses) ---

class Attestation(BaseModel):
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
    attestation: Attestation
    message: str = "Attestation created successfully"


class RevokeResponse(BaseModel):
    attestation: Attestation
    message: str = "Attestation revoked successfully"


class VerifyResponse(BaseModel):
    attestation: Attestation
    verified: bool = True


class ErrorResponse(BaseModel):
    error: str
    existing_attestation: Attestation | None = None
