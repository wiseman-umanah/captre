"""
shared/captre_client.py — HTTP client for the Captre attestation API.

Handles the full x402 payment handshake automatically using x402ClientSync.
The caller only needs a wallet and the content to attest — this module manages
the 402 challenge, payment payload construction, and retry.

API surface exposed:
  attest(wallet, content_hash, **fields) -> dict
  revoke(wallet, attestation_id)         -> dict
  verify(content_hash)                   -> dict | None  (free, no wallet needed)
  get_attestation(attestation_id)        -> dict | None  (free, no wallet needed)
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from x402 import parse_payment_required, x402ClientSync
from x402.mechanisms.avm.exact.register import register_exact_avm_client

from shared.wallet import AlgorandWallet

# ─── Exceptions ────────────────────────────────────────────────────────────

class AttestError(Exception):
    """Raised when POST /attest fails (including duplicate 409)."""


class DuplicateClaimError(AttestError):
    """Raised when the content_hash has already been claimed (409)."""

    def __init__(self, existing: dict[str, Any]) -> None:
        """
        Construct a DuplicateClaimError.

        Parameters
        ----------
        existing : dict
            The existing attestation record returned in the 409 body.
        """
        super().__init__("content_hash already claimed")
        self.existing = existing


class RevokeError(Exception):
    """Raised when POST /revoke fails."""


class NotFoundError(Exception):
    """Raised when a verify or get_attestation lookup returns 404."""


# ─── Internal helpers ───────────────────────────────────────────────────────

def _build_x402_client(wallet: AlgorandWallet, algod_url: str) -> x402ClientSync:
    """
    Build an x402ClientSync wired to an agent wallet.

    Parameters
    ----------
    wallet : AlgorandWallet
        The agent's wallet — used to sign the payment transaction.
    algod_url : str
        Algod node URL passed to ExactAvmScheme for transaction building.

    Returns
    -------
    x402ClientSync
        Configured client ready to create payment payloads.
    """
    client = x402ClientSync()
    register_exact_avm_client(client, wallet, algod_url=algod_url)
    return client


def _do_paid_post(
    http: httpx.Client,
    x402_client: x402ClientSync,
    url: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    POST to a Captre x402-protected endpoint with automatic payment retry.

    Flow:
      1. POST → 402? parse PaymentRequired from X-Payment-Required header.
      2. Create PaymentPayload via x402ClientSync.
      3. Retry POST with X-Payment-Payload header.
      4. Return parsed JSON body on 200/201.

    Parameters
    ----------
    http : httpx.Client
        Shared HTTP client (keeps connection alive across calls).
    x402_client : x402ClientSync
        Pre-configured x402 client for this agent's wallet.
    url : str
        Full URL of the paid endpoint.
    body : dict[str, Any]
        JSON request body.

    Returns
    -------
    dict[str, Any]
        Parsed JSON response body on success.

    Raises
    ------
    httpx.HTTPStatusError
        For any non-402/non-2xx status on the final request.
    """
    # ── First attempt ────────────────────────────────────────────────────
    resp = http.post(url, json=body)

    if resp.status_code != 402:
        resp.raise_for_status()
        return resp.json()

    # ── Handle 402 ───────────────────────────────────────────────────────
    # Captre's x402 middleware puts the challenge in the `payment-required`
    # header as a base64-encoded JSON blob (not X-Payment-Required, not raw JSON).
    import base64 as _b64
    raw_header = resp.headers.get("payment-required")
    if raw_header:
        # base64 → bytes → parse
        decoded = _b64.b64decode(raw_header)
    else:
        # fallback: body is the challenge (some x402 server versions)
        decoded = resp.content
    payment_required = parse_payment_required(decoded)
    payload = x402_client.create_payment_payload(payment_required)

    # ── Retry with payment ───────────────────────────────────────────────
    # Server reads "PAYMENT-SIGNATURE" header (from x402 constants).
    # Value must be base64-encoded JSON (matching decode_payment_signature_header).
    import base64 as _b64e
    payload_json = payload.model_dump_json() if hasattr(payload, "model_dump_json") else json.dumps(payload)
    payload_b64 = _b64e.b64encode(payload_json.encode()).decode()
    retry = http.post(
        url,
        json=body,
        headers={"PAYMENT-SIGNATURE": payload_b64},
    )
    retry.raise_for_status()
    return retry.json()


# ─── Public API ─────────────────────────────────────────────────────────────

def attest(
    wallet: AlgorandWallet,
    content_hash: str,
    agent_id: str | None = None,
    output_type: str | None = None,
    description: str | None = None,
    model: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
    previous_attestation: str | None = None,
    base_url: str = "",
    algod_url: str = "",
) -> dict[str, Any]:
    """
    Attest a content hash via POST /attest, paying with the agent's wallet.

    Parameters
    ----------
    wallet : AlgorandWallet
        The agent wallet that will sign and pay the x402 fee.
    content_hash : str
        SHA-256 hash of the content (e.g. ``sha256:abc123...``).
    agent_id : str or None
        Optional identifier for this agent.
    output_type : str or None
        Content category: ``research``, ``code``, ``decision``, ``file``,
        ``report``, or ``other``.
    description : str or None
        Human-readable description of the attested content.
    model : str or None
        AI model name that produced the content.
    tags : list[str] or None
        Free-form tags.
    extra : dict or None
        Arbitrary extra metadata.
    previous_attestation : str or None
        attestation_id this one supersedes.
    base_url : str
        Captre server base URL. Falls back to ``CAPTRE_BASE_URL`` env var.
    algod_url : str
        Algod node URL. Falls back to ``ALGOD_URL`` env var.

    Returns
    -------
    dict[str, Any]
        Full ``AttestResponse`` body from the server.

    Raises
    ------
    DuplicateClaimError
        If the content_hash has already been claimed (409).
    AttestError
        If the attestation fails for any other reason.
    """
    base_url = base_url or os.environ["CAPTRE_BASE_URL"]
    algod_url = algod_url or os.environ["ALGOD_URL"]

    body: dict[str, Any] = {"content_hash": content_hash}
    if agent_id:
        body["agent_id"] = agent_id
    if output_type:
        body["output_type"] = output_type
    if description:
        body["description"] = description
    if model:
        body["model"] = model
    if tags:
        body["tags"] = tags
    if extra:
        body["extra"] = extra
    if previous_attestation:
        body["previous_attestation"] = previous_attestation

    x402_client = _build_x402_client(wallet, algod_url)
    with httpx.Client(timeout=30) as http:
        try:
            return _do_paid_post(http, x402_client, f"{base_url}/attest", body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                detail = exc.response.json().get("detail", {})
                existing = detail.get("existing_attestation", {}) if isinstance(detail, dict) else {}
                raise DuplicateClaimError(existing) from exc
            raise AttestError(
                f"attest failed {exc.response.status_code}: {exc.response.text}"
            ) from exc


def revoke(
    wallet: AlgorandWallet,
    attestation_id: str,
    base_url: str = "",
    algod_url: str = "",
) -> dict[str, Any]:
    """
    Revoke an attestation via POST /revoke, paying with the agent's wallet.

    The wallet must be the original author of the attestation.

    Parameters
    ----------
    wallet : AlgorandWallet
        The agent wallet that originally attested (must match ``author`` on chain).
    attestation_id : str
        UUID or content_hash of the attestation to revoke.
    base_url : str
        Captre server base URL. Falls back to ``CAPTRE_BASE_URL`` env var.
    algod_url : str
        Algod node URL. Falls back to ``ALGOD_URL`` env var.

    Returns
    -------
    dict[str, Any]
        Full ``RevokeResponse`` body from the server.

    Raises
    ------
    RevokeError
        If the revocation fails (e.g. 403 not the author, 404 not found).
    """
    base_url = base_url or os.environ["CAPTRE_BASE_URL"]
    algod_url = algod_url or os.environ["ALGOD_URL"]

    x402_client = _build_x402_client(wallet, algod_url)
    with httpx.Client(timeout=30) as http:
        try:
            return _do_paid_post(
                http, x402_client,
                f"{base_url}/revoke",
                {"attestation_id": attestation_id},
            )
        except httpx.HTTPStatusError as exc:
            raise RevokeError(
                f"revoke failed {exc.response.status_code}: {exc.response.text}"
            ) from exc


def verify(
    content_hash: str,
    base_url: str = "",
) -> dict[str, Any] | None:
    """
    Look up an attestation by content_hash via GET /verify (free endpoint).

    Parameters
    ----------
    content_hash : str
        The hash to verify.
    base_url : str
        Captre server base URL. Falls back to ``CAPTRE_BASE_URL`` env var.

    Returns
    -------
    dict[str, Any] or None
        Full ``VerifyResponse`` body, or ``None`` if not found (404).
    """
    base_url = base_url or os.environ["CAPTRE_BASE_URL"]
    with httpx.Client(timeout=15) as http:
        resp = http.get(f"{base_url}/verify", params={"content_hash": content_hash})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def get_attestation(
    attestation_id: str,
    base_url: str = "",
) -> dict[str, Any] | None:
    """
    Retrieve an attestation by UUID or content_hash via GET /attestation/:id (free).

    Parameters
    ----------
    attestation_id : str
        UUID ``attestation_id`` or raw ``content_hash``.
    base_url : str
        Captre server base URL. Falls back to ``CAPTRE_BASE_URL`` env var.

    Returns
    -------
    dict[str, Any] or None
        Full ``VerifyResponse`` body, or ``None`` if not found (404).
    """
    base_url = base_url or os.environ["CAPTRE_BASE_URL"]
    with httpx.Client(timeout=15) as http:
        resp = http.get(f"{base_url}/attestation/{attestation_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
