"""
agents/critic.py — CriticAgent

Simulates an adversarial agent that:
  1. Produces a claim (a "decision") and attests it.
  2. Later discovers it was wrong and revokes it (demonstrating self-revocation).
  3. Issues a corrected decision and attests that instead.
  4. Tries to verify the auditor's report (cross-agent curiosity).

Demonstrates the full attest → revoke → re-attest lifecycle
and cross-agent verification without payment.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared.captre_client import DuplicateClaimError, attest, get_attestation, revoke
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet


class CriticAgent:
    """
    An agent that attests, retracts, and cross-verifies other agents' work.

    Attributes
    ----------
    name : str
        Display name used in log lines.
    wallet : AlgorandWallet
        The agent's Algorand wallet.
    """

    name = "CRITIC"

    def __init__(self, wallet: AlgorandWallet) -> None:
        """
        Construct the CriticAgent.

        Parameters
        ----------
        wallet : AlgorandWallet
            The funded wallet for this agent.
        """
        self.wallet = wallet
        self._attestations: list[dict[str, Any]] = []

    def run(self, registry: dict[str, list[dict[str, Any]]]) -> None:
        """
        Execute the full critic lifecycle.

        Issues an initial decision, revokes it, issues a correction,
        then inspects the auditor's report if available.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry. Key ``"critic"`` is populated with
            this agent's attestation records.
        """
        registry.setdefault("critic", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")

        ts1 = datetime.now(tz=timezone.utc).isoformat()
        initial_decision = (
            f"DECISION {ts1}: Deploy model version 3.1 to production. "
            "Confidence: HIGH based on 94% test accuracy."
        )
        h1 = sha256(initial_decision)

        # ── Attest initial decision ─────────────────────────────────────
        log(self.name, "ATTEST", "Attesting initial deployment decision", detail=h1[:30] + "…")
        initial_record: dict[str, Any] | None = None
        try:
            resp = attest(
                wallet=self.wallet,
                content_hash=h1,
                agent_id="critic-agent-v1",
                output_type="decision",
                description="Initial deployment decision for model v3.1",
                tags=["decision", "deployment", "automated"],
                extra={"confidence": "HIGH", "model_version": "3.1"},
            )
            initial_record = resp["attestation"]
            self._attestations.append(initial_record)
            registry["critic"].append(initial_record)
            log(
                self.name, "SUCCESS",
                "Initial decision attested",
                detail=f"id={initial_record['attestation_id'][:8]}…",
            )
        except DuplicateClaimError as exc:
            log(self.name, "INFO", "Initial decision already claimed (re-run). Skipping.")
            initial_record = exc.existing
        except Exception as exc:
            log(self.name, "ERROR", f"Failed to attest initial decision: {exc}")

        time.sleep(3)

        # ── Revoke — model failed validation ────────────────────────────
        if initial_record:
            log(
                self.name, "REVOKE",
                "RETRACTING — model v3.1 failed validation on staging. DO NOT DEPLOY.",
                detail=f"id={initial_record['attestation_id'][:8]}…",
            )
            try:
                revoke(wallet=self.wallet, attestation_id=initial_record["attestation_id"])
                log(self.name, "SUCCESS", "Revocation confirmed. Decision invalidated on-chain.")
                initial_record["status"] = "revoked"
            except Exception as exc:
                log(self.name, "ERROR", f"Revocation failed: {exc}")

        time.sleep(2)

        # ── Attest corrected decision ────────────────────────────────────
        ts2 = datetime.now(tz=timezone.utc).isoformat()
        corrected_decision = (
            f"DECISION {ts2}: DO NOT deploy model v3.1. "
            "Validation failure detected: 23% regression on edge-case benchmark. "
            "Rollback to v2.9 recommended."
        )
        h2 = sha256(corrected_decision)
        prev_id = initial_record["attestation_id"] if initial_record else None

        log(self.name, "ATTEST", "Attesting corrected decision", detail=h2[:30] + "…")
        try:
            resp = attest(
                wallet=self.wallet,
                content_hash=h2,
                agent_id="critic-agent-v1",
                output_type="decision",
                description="CORRECTED: Do not deploy model v3.1 — validation failure",
                tags=["decision", "correction", "automated"],
                previous_attestation=prev_id,
                extra={"confidence": "HIGH", "model_version": "3.1", "action": "rollback"},
            )
            corrected_record = resp["attestation"]
            self._attestations.append(corrected_record)
            registry["critic"].append(corrected_record)
            log(
                self.name, "SUCCESS",
                "Corrected decision attested",
                detail=f"id={corrected_record['attestation_id'][:8]}…",
            )
        except DuplicateClaimError:
            log(self.name, "INFO", "Corrected decision already on-chain.")
        except Exception as exc:
            log(self.name, "ERROR", f"Failed to attest correction: {exc}")

        time.sleep(2)

        # ── Cross-verify the auditor's report (curiosity) ────────────────
        auditor_records = registry.get("auditor", [])
        if auditor_records:
            audit_id = auditor_records[0]["attestation_id"]
            log(self.name, "VERIFY", "Reading auditor's report from chain…", detail=f"id={audit_id[:8]}…")
            result = get_attestation(audit_id)
            if result:
                a = result["attestation"]
                log(
                    self.name, "INFO",
                    f"Auditor report: status={a['status']} "
                    f"verified={a.get('extra', {}).get('verified', '?')} "
                    f"revoked={a.get('extra', {}).get('revoked', '?')}",
                )
            else:
                log(self.name, "INFO", "Auditor report not yet on-chain.")
        else:
            log(self.name, "WAIT", "Auditor report not yet available in registry.")

        log(self.name, "INFO", "Done.")
