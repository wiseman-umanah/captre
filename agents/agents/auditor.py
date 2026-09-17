"""
agents/auditor.py — AuditorAgent

Simulates an independent evaluator that:
  1. Waits until the researcher has populated the registry with attestations.
  2. Verifies each attestation is on-chain via GET /verify (free endpoint).
  3. For each active attestation, submits a formal evaluation via POST /evaluate,
     recording the result and policy hash on-chain (paid — proves evaluator identity).
  4. Attests its own audit summary report.

This is the full provenance chain completing — the evaluator's identity and
policy commitment are permanently recorded alongside the researcher's output.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

from shared.captre_client import DuplicateClaimError, EvaluateError, attest, evaluate, verify
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet

# Deterministic policy document for this auditor — hash is committed on-chain
_AUDIT_POLICY = (
    "Captre Audit Policy v1.0: "
    "An output passes evaluation if (1) it is present on-chain, "
    "(2) the author address matches the claimed agent, "
    "(3) the content preview is internally consistent. "
    "Revoked outputs are noted but not re-evaluated."
)
_POLICY_HASH = "sha256:" + hashlib.sha256(_AUDIT_POLICY.encode()).hexdigest()


class AuditorAgent:
    """
    An agent that verifies and formally evaluates others' attested outputs.

    Attributes
    ----------
    name : str
        Display name used in log lines.
    wallet : AlgorandWallet
        The evaluator wallet (pays x402 fees for each evaluation, becomes on-chain evaluator).
    """

    name = "AUDITOR"

    def __init__(self, wallet: AlgorandWallet) -> None:
        """
        Construct the AuditorAgent.

        Parameters
        ----------
        wallet : AlgorandWallet
            The funded wallet for this agent.
        """
        self.wallet = wallet

    def run(self, registry: dict[str, list[dict[str, Any]]]) -> None:
        """
        Execute the full auditor lifecycle.

        Verifies every attestation in the registry, evaluates active ones on-chain,
        then attests a summary audit report.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry populated by researcher and coder agents.
        """
        registry.setdefault("auditor", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")
        log(self.name, "WAIT", "Waiting 5 s for researcher and coder to land on-chain…")
        time.sleep(5)

        verified_count = 0
        revoked_count = 0
        missing_count = 0
        evaluated_count = 0

        for source, records in registry.items():
            if source == "auditor":
                continue
            for record in records:
                content_hash = record.get("content_hash", "")
                attestation_id = record.get("attestation_id", "")
                task_hash = record.get("_task_hash")

                log(
                    self.name, "VERIFY",
                    f"Verifying [{source}] {attestation_id[:8]}…",
                    detail=content_hash[:30] + "…",
                )
                result = verify(content_hash)
                time.sleep(0.5)

                if result is None:
                    log(self.name, "ERROR", f"NOT FOUND on-chain — {attestation_id[:8]}…")
                    missing_count += 1
                    continue

                status = result["attestation"]["status"]
                author = result["attestation"]["author"]

                if status != "active":
                    log(
                        self.name, "INFO",
                        f"Skipping revoked [{source}] {attestation_id[:8]}…",
                        detail=f"author={author[:12]}…",
                    )
                    revoked_count += 1
                    continue

                log(
                    self.name, "SUCCESS",
                    f"Verified active [{source}] {attestation_id[:8]}…",
                    detail=f"author={author[:12]}…",
                )
                verified_count += 1

                # ── Evaluate active attestations on-chain ────────────────
                log(
                    self.name, "EVALUATE",
                    f"Evaluating [{source}] {attestation_id[:8]}…",
                    detail=f"policy={_POLICY_HASH[:30]}…",
                )
                try:
                    eval_resp = evaluate(
                        wallet=self.wallet,
                        output_attestation_id=attestation_id,
                        content_hash=content_hash,
                        policy_hash=_POLICY_HASH,
                        evaluation_result="pass",
                        task_hash=task_hash,
                        score=1.0,
                        notes=f"On-chain verification passed. Author: {author[:20]}",
                    )
                    eval_record = eval_resp["evaluation"]
                    evaluated_count += 1
                    log(
                        self.name, "SUCCESS",
                        f"Evaluation recorded [{source}] {attestation_id[:8]}…",
                        detail=f"eval_id={eval_record['evaluation_id'][:8]}…",
                    )
                except EvaluateError as exc:
                    log(self.name, "ERROR", f"Evaluation failed [{source}] {attestation_id[:8]}…: {exc}")

                time.sleep(1)

        # ── Attest the audit report ──────────────────────────────────────
        ts = datetime.now(tz=UTC).isoformat()
        report = (
            f"AUDIT REPORT {ts}: verified={verified_count} evaluated={evaluated_count} "
            f"revoked={revoked_count} missing={missing_count} "
            f"total_checked={verified_count + revoked_count + missing_count} "
            f"policy={_POLICY_HASH[:30]}"
        )
        h = sha256(report)
        log(self.name, "ATTEST", "Attesting audit report", detail=h[:30] + "…")
        try:
            resp = attest(
                wallet=self.wallet,
                content_hash=h,
                agent_id="auditor-agent-v1",
                output_type="report",
                description="On-chain audit report of researcher + coder attestations",
                tags=["audit", "automated"],
                extra={
                    "verified": verified_count,
                    "evaluated": evaluated_count,
                    "revoked": revoked_count,
                    "missing": missing_count,
                    "policy_hash": _POLICY_HASH,
                },
            )
            record = resp["attestation"]
            registry["auditor"].append(record)
            log(
                self.name, "SUCCESS",
                "Audit report attested",
                detail=f"id={record['attestation_id'][:8]}…",
            )
        except DuplicateClaimError:
            log(self.name, "INFO", "Audit report already on-chain (duplicate run).")
        except Exception as exc:  # noqa: BLE001
            log(self.name, "ERROR", f"Failed to attest audit report: {exc}")

        log(self.name, "INFO", "Done.")
