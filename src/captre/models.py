"""
Pydantic schemas for Captre request bodies, stored records, and API responses.

All field names match the PRD §5 specification exactly. Do not rename them —
the same names are used as box-storage JSON keys on-chain.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


class EvaluationResult(str, Enum):
    """Settlement outcome of an evaluation written to LedgerApp."""

    pass_ = "pass"
    fail = "fail"
    partial = "partial"
    score_only = "score_only"


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
    task_hash : str or None
        Optional SHA-256 hash of the task whose output is being attested,
        e.g. ``sha256:abc123...``. When supplied, the settlement layer verifies
        a matching ``TaskRecord`` exists in ``TaskApp`` before writing.
    content_cid : str or None
        Optional IPFS / Filecoin CID pointing to the full content. Private
        inputs stay off-chain; only the hash and CID pointer go on-chain.
    policy_version : str or None
        Optional human-readable label for the policy under which this output
        was produced (e.g. ``"v2.1"``). For binding policy commitments use
        ``policy_hash`` in the evaluation record instead.
    """

    content_hash: str = Field(..., description="SHA-256 hash of the content, e.g. sha256:abc123...")
    agent_id: str | None = None
    output_type: OutputType | None = None
    description: str | None = None
    model: str | None = None
    previous_attestation: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    task_hash: str | None = None
    content_cid: str | None = None
    policy_version: str | None = None


class SubmitTaskRequest(BaseModel):
    """
    Body of a POST /submit-task request.

    Attributes
    ----------
    content : str
        The raw task content (prompt, specification, instruction set, etc.).
        Its SHA-256 hash is used as the on-chain box key — only the hash goes
        on-chain; the content itself stays off-chain.
    agent_id : str or None
        Optional identifier for the agent or system that will execute the task.
    description : str or None
        Human-readable description of the task.
    tags : list[str]
        Free-form tags for discovery and filtering. Defaults to ``[]``.
    extra : dict[str, Any]
        Arbitrary key/value metadata. Defaults to ``{}``.
    """

    content: str = Field(..., description="Raw task content whose SHA-256 hash is stored on-chain")
    agent_id: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    """
    Body of a POST /evaluate request.

    The evaluator identity is NOT a field here — it is derived from the x402
    payment payer address, exactly like ``author`` in ``AttestRequest``. This
    is what makes the evaluator identity cryptographically proven rather than
    self-reported.

    Attributes
    ----------
    output_attestation_id : str
        UUID ``attestation_id`` of the output attestation being evaluated.
        Used to look up the ``content_hash`` from the on-chain id_index.
    content_hash : str
        SHA-256 hash of the attested output, e.g. ``sha256:abc123...``.
        Must match an existing attestation in ``CaptreApp``.
    task_hash : str or None
        Optional SHA-256 hash of the originating task, e.g. ``sha256:...``.
        When supplied, the settlement layer verifies a matching ``TaskRecord``
        exists in ``TaskApp`` before writing, and ``LedgerApp`` cross-calls
        ``TaskApp.task_exists()`` on-chain.
    policy_hash : str
        SHA-256 hash of the policy document under which the evaluation was
        performed, formatted as ``sha256:<64 hex chars>``. The caller hashes
        their policy document and submits that digest — this creates an
        immutable on-chain commitment to a specific ruleset, not just a label.
    evaluation_result : EvaluationResult
        Settlement outcome: ``pass``, ``fail``, ``partial``, or ``score_only``.
    score : float or None
        Optional numeric score (0.0–1.0). Required when
        ``evaluation_result == "score_only"``.
    notes : str or None
        Optional human-readable notes about the evaluation. Stored on-chain
        inside the JSON blob.
    """

    output_attestation_id: str
    content_hash: str
    task_hash: str | None = None
    policy_hash: str = Field(..., description="sha256:<64 hex chars> of the policy document")
    evaluation_result: EvaluationResult
    score: float | None = None
    notes: str | None = None

    @field_validator("policy_hash")
    @classmethod
    def _validate_policy_hash(cls, v: str) -> str:
        """
        Validate that ``policy_hash`` is a properly formatted SHA-256 digest.

        Parameters
        ----------
        v : str
            The raw field value to validate.

        Returns
        -------
        str
            The validated value, unchanged.

        Raises
        ------
        ValueError
            If ``v`` does not start with ``"sha256:"`` followed by exactly
            64 lowercase hexadecimal characters.
        """
        prefix = "sha256:"
        if not v.startswith(prefix):
            raise ValueError("policy_hash must start with 'sha256:'")
        hex_part = v[len(prefix):]
        if len(hex_part) != 64 or not all(c in "0123456789abcdef" for c in hex_part):
            raise ValueError(
                "policy_hash must be 'sha256:' followed by exactly 64 lowercase hex chars"
            )
        return v


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


# --- Stored records (written to box / returned in responses) ---

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
    task_hash : str or None
        Optional hash of the originating task. When present, a matching
        ``TaskRecord`` was verified to exist in ``TaskApp`` at attest time.
    content_cid : str or None
        Optional IPFS / Filecoin CID pointing to the full content.
    policy_version : str or None
        Optional human-readable policy label forwarded from the request.
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
    task_hash: str | None = None
    content_cid: str | None = None
    policy_version: str | None = None


class TaskRecord(BaseModel):
    """
    Full task record — written to ``TaskApp`` box storage as JSON and returned
    verbatim in API responses.

    Attributes
    ----------
    task_id : str
        Server-generated UUID assigned at submit time.
    author : str
        Algorand address of the x402 payment payer. Proven by wallet
        signature — never self-reported.
    created_at : datetime
        UTC timestamp of when the task was written on-chain.
    tx_id : str
        Payment group ID from the x402 settlement.
    task_hash : str
        ``sha256:<hex>`` hash of the raw ``content`` field. Used as the
        on-chain box key (after a second SHA-256 digest to fit in 32 bytes).
    agent_id : str or None
        Optional identifier for the agent or system that will execute the task.
    description : str or None
        Human-readable description of the task.
    tags : list[str]
        Free-form tags.
    extra : dict[str, Any]
        Arbitrary key/value metadata.
    """

    # server-controlled
    task_id: str
    author: str
    created_at: datetime
    tx_id: str
    task_hash: str

    # client-supplied
    agent_id: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class EvaluationRecord(BaseModel):
    """
    Full evaluation record — written to ``LedgerApp`` box storage as JSON and
    returned verbatim in API responses.

    Attributes
    ----------
    evaluation_id : str
        Server-generated UUID assigned at evaluation time.
    created_at : datetime
        UTC timestamp of when the evaluation was written on-chain.
    tx_id : str
        Payment group ID from the x402 settlement. The evaluator's wallet
        signed this transaction — proves evaluator identity on-chain.
    output_attestation_id : str
        UUID of the output attestation being evaluated.
    content_hash : str
        SHA-256 hash of the attested output, matching the ``CaptreApp`` record.
    task_hash : str or None
        Optional SHA-256 hash of the originating task. When present, a matching
        ``TaskRecord`` was verified to exist in ``TaskApp`` at evaluation time.
    evaluator : str
        Algorand address of the x402 payment payer. Proven by wallet
        signature — never sourced from the request body.
    policy_hash : str
        ``sha256:<64 hex chars>`` of the policy document under which the
        evaluation was performed. Immutable commitment — not just a label.
    evaluation_result : EvaluationResult
        Settlement outcome: ``pass``, ``fail``, ``partial``, or ``score_only``.
    score : float or None
        Optional numeric score.
    notes : str or None
        Optional human-readable notes stored on-chain.
    """

    # server-controlled
    evaluation_id: str
    created_at: datetime
    tx_id: str

    # derived from request + payer
    output_attestation_id: str
    content_hash: str
    task_hash: str | None = None
    evaluator: str        # from x402 payer — never from request body
    policy_hash: str
    evaluation_result: EvaluationResult
    score: float | None = None
    notes: str | None = None


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


class SubmitTaskResponse(BaseModel):
    """
    Response body for a successful POST /submit-task.

    Attributes
    ----------
    task : TaskRecord
        The newly created task record.
    message : str
        Human-readable confirmation. Defaults to ``"Task submitted successfully"``.
    """

    task: TaskRecord
    message: str = "Task submitted successfully"


class EvaluateResponse(BaseModel):
    """
    Response body for a successful POST /evaluate.

    Attributes
    ----------
    evaluation : EvaluationRecord
        The newly created evaluation record.
    message : str
        Human-readable confirmation. Defaults to
        ``"Evaluation recorded successfully"``.
    """

    evaluation: EvaluationRecord
    message: str = "Evaluation recorded successfully"
