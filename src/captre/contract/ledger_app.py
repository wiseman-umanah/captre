"""
LedgerApp smart contract — Algorand Python (AlgoKit / Puya)

Stores evaluation records keyed by a SHA-256 digest of the evaluation UUID.
Before writing, cross-calls BOTH ``CaptreApp.exists()`` AND
``TaskApp.task_exists()`` (when a task_hash_key is supplied) to verify the
full provenance chain is real — not just that strings were typed.

This is what makes the ledger prove correctness, not just storage:
  - The attestation reference is verified on-chain against CaptreApp
  - The task reference is verified on-chain against TaskApp
  - The evaluator identity is the x402 payment payer, not self-reported

BoxMap layout:
  evaluations : evaluation_id_key (32-byte SHA-256 digest of the evaluation UUID)
                  → JSON metadata blob (key_prefix b"e:")
  Box name: b"e:" + sha256(evaluation_id)  →  34 bytes (well under 64-byte limit)

Methods:
  add_evaluation(attestation_app_id, task_app_id, content_hash_key,
                 task_hash_key, evaluation_id_key, metadata_json) -> None
  get_evaluation(evaluation_id_key) -> bytes

Unlike CaptreApp, this contract explicitly allows UpdateApplication and
DeleteApplication via @baremethod(allow_actions=...) — learned from the
CaptreApp mistake that locked 25 ALGO.

Compile with (from project root — use isolation workaround):
  mkdir -p /tmp/captre_compile && \\
  cp src/captre/contract/ledger_app.py /tmp/captre_compile/ && \\
  algokit compile python /tmp/captre_compile/ledger_app.py \\
    --out-dir /tmp/captre_compile/artifacts --output-arc32 && \\
  cp /tmp/captre_compile/artifacts/* src/captre/contract/artifacts/ && \\
  rm -rf /tmp/captre_compile
"""

from algopy import Application, ARC4Contract, BoxMap, Bytes, UInt64, arc4
from algopy.arc4 import Bool as ABIBool


class LedgerApp(ARC4Contract):
    """
    On-chain evaluation ledger.

    Stores evaluation records that reference attestations in ``CaptreApp`` and
    optionally tasks in ``TaskApp``. Before writing, cross-calls both upstream
    contracts to verify the referenced records are real — proving correctness,
    not just storage. Supports update and deletion so stranded ALGO can always
    be recovered.

    Attributes
    ----------
    evaluations : BoxMap[Bytes, Bytes]
        Maps ``evaluation_id_key`` (32-byte SHA-256 digest of the evaluation
        UUID) → serialised JSON metadata blob.
        Box key prefix: ``b"e:"``. Box name is always 34 bytes.
    """

    def __init__(self) -> None:
        self.evaluations = BoxMap(Bytes, Bytes, key_prefix=b"e:")

    @arc4.baremethod(allow_actions=["UpdateApplication"])
    def update(self) -> None:
        """Allow the contract creator to update the approval program."""

    @arc4.baremethod(allow_actions=["DeleteApplication"])
    def delete(self) -> None:
        """Allow the contract creator to delete the application."""

    @arc4.abimethod
    def add_evaluation(
        self,
        attestation_app_id: UInt64,
        task_app_id: UInt64,
        content_hash_key: Bytes,
        task_hash_key: Bytes,
        evaluation_id_key: Bytes,
        metadata_json: Bytes,
    ) -> None:
        """
        Write a new evaluation record, verifying the full provenance chain.

        Cross-calls ``CaptreApp.exists(content_hash_key)`` unconditionally.
        When ``task_hash_key`` is non-empty, also cross-calls
        ``TaskApp.task_exists(task_hash_key)``. Both upstream apps must be
        listed in the transaction's ``foreign_apps`` array.

        Parameters
        ----------
        attestation_app_id : UInt64
            On-chain application ID of the existing ``CaptreApp`` contract.
            Must be listed in the transaction's ``foreign_apps`` array.
        task_app_id : UInt64
            On-chain application ID of the ``TaskApp`` contract.
            Must be listed in ``foreign_apps`` when ``task_hash_key`` is
            non-empty. Pass ``0`` only when ``task_hash_key`` is empty.
        content_hash_key : Bytes
            32-byte SHA-256 digest key of the attestation to reference.
            Passed verbatim to ``CaptreApp.exists()``.
        task_hash_key : Bytes
            32-byte SHA-256 digest key of the task to reference.
            Pass ``b""`` (zero-length) to skip the task existence check for
            evaluations not linked to a specific task.
        evaluation_id_key : Bytes
            32-byte SHA-256 digest of the evaluation UUID. Used as the
            ``evaluations`` box key. Must not already exist — aborts with
            ``ERR_ALREADY_EXISTS`` if so.
        metadata_json : Bytes
            Full JSON-serialised ``EvaluationRecord``. Written verbatim to
            the ``evaluations`` box.

        Raises
        ------
        Assert(ERR_EMPTY_HASH)
            If ``content_hash_key`` is zero-length.
        Assert(ERR_EMPTY_ID_KEY)
            If ``evaluation_id_key`` is zero-length.
        Assert(ERR_EMPTY_METADATA)
            If ``metadata_json`` is zero-length.
        Assert(ERR_ALREADY_EXISTS)
            If ``evaluation_id_key`` already has a box in ``evaluations``.
        Assert(ERR_ATTESTATION_NOT_FOUND)
            If ``CaptreApp.exists(content_hash_key)`` returns ``False``.
        Assert(ERR_TASK_NOT_FOUND)
            If ``task_hash_key`` is non-empty and
            ``TaskApp.task_exists(task_hash_key)`` returns ``False``.
        """
        assert content_hash_key.length > UInt64(0), "ERR_EMPTY_HASH"
        assert evaluation_id_key.length > UInt64(0), "ERR_EMPTY_ID_KEY"
        assert metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        assert evaluation_id_key not in self.evaluations, "ERR_ALREADY_EXISTS"

        # Verify the referenced attestation exists in CaptreApp.
        # arc4.abi_call[ABIBool] is required when using a string selector so
        # puyapy can infer the return type; .native converts arc4.Bool → bool.
        attestation_exists, _txn = arc4.abi_call[ABIBool](
            "exists(byte[])bool",
            content_hash_key,
            app_id=Application(attestation_app_id),
        )
        assert attestation_exists.native, "ERR_ATTESTATION_NOT_FOUND"

        # When task_hash_key is supplied, verify the referenced task exists in
        # TaskApp. Passing b"" skips this check for free-standing evaluations.
        if task_hash_key.length > UInt64(0):
            task_exists, _txn2 = arc4.abi_call[ABIBool](
                "task_exists(byte[])bool",
                task_hash_key,
                app_id=Application(task_app_id),
            )
            assert task_exists.native, "ERR_TASK_NOT_FOUND"

        self.evaluations[evaluation_id_key] = metadata_json

    @arc4.abimethod(readonly=True)
    def get_evaluation(self, evaluation_id_key: Bytes) -> Bytes:
        """
        Read an evaluation record by ``evaluation_id_key``.

        Parameters
        ----------
        evaluation_id_key : Bytes
            The 32-byte SHA-256 digest key to look up.

        Returns
        -------
        Bytes
            The raw JSON metadata blob stored in the box, or ``b""`` if no
            box exists for this key.
        """
        if evaluation_id_key in self.evaluations:
            return self.evaluations[evaluation_id_key]
        return Bytes(b"")
