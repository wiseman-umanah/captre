"""
agents/auditor.py — AuditorAgent

Simulates a verification-only agent that:
  1. Waits until the researcher and coder have populated the registry.
  2. Iterates every attestation in the registry and verifies each one
     by calling GET /verify on Captre (free endpoint, no payment).
  3. Reports what it found: active, revoked, or missing.
  4. Attests its own audit report summarising the findings.

The auditor pays for ONE attestation (its report) but all verification
calls are free — demonstrating the asymmetry of the platform.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared.captre_client import DuplicateClaimError, attest, verify
from shared.hashing import sha256
from shared.log import log
from shared.wallet import AlgorandWallet


class AuditorAgent:
    """
    An agent that verifies others' claims and attests an audit summary.

    Attributes
    ----------
    name : str
        Display name used in log lines.
    wallet : AlgorandWallet
        The agent's Algorand wallet (used only for the audit report attestation).
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

        Verifies every attestation in the registry, then attests a one-line
        summary of the audit results. Appends its report attestation to
        ``registry["auditor"]``.

        Parameters
        ----------
        registry : dict[str, list[dict]]
            Shared world registry populated by researcher and coder agents.
        """
        registry.setdefault("auditor", [])
        log(self.name, "INFO", f"Starting — wallet {self.wallet.address[:12]}…")
        log(self.name, "WAIT", "Waiting 3 s for researcher and coder to land on-chain…")
        time.sleep(3)

        verified_count = 0
        revoked_count = 0
        missing_count = 0
        all_records: list[dict[str, Any]] = []

        for source, records in registry.items():
            if source == "auditor":
                continue
            for record in records:
                content_hash = record.get("content_hash", "")
                attestation_id = record.get("attestation_id", "")

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
                else:
                    status = result["attestation"]["status"]
                    author = result["attestation"]["author"]
                    if status == "active":
                        log(
                            self.name, "SUCCESS",
                            f"Verified active  [{source}] {attestation_id[:8]}…",
                            detail=f"author={author[:12]}…",
                        )
                        verified_count += 1
                    else:
                        log(
                            self.name, "INFO",
                            f"Verified revoked [{source}] {attestation_id[:8]}…",
                            detail=f"author={author[:12]}…",
                        )
                        revoked_count += 1
                    all_records.append(result["attestation"])

        # ── Attest the audit report ──────────────────────────────────────
        ts = datetime.now(tz=timezone.utc).isoformat()
        report = (
            f"AUDIT REPORT {ts}: verified={verified_count} revoked={revoked_count} "
            f"missing={missing_count} total_checked={verified_count + revoked_count + missing_count}"
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
                    "revoked": revoked_count,
                    "missing": missing_count,
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
        except Exception as exc:
            log(self.name, "ERROR", f"Failed to attest audit report: {exc}")

        log(self.name, "INFO", "Done.")
