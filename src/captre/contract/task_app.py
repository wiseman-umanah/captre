"""
TaskApp smart contract — Algorand Python (AlgoKit / Puya)

Stores task submissions as first-claim records keyed by a SHA-256 digest of the
task content string. Mirrors the CaptreApp attestation scheme but is a separate
contract that can be updated and deleted.

BoxMap layout:
  tasks : task_hash_key (32-byte SHA-256 digest of the task content string)
            → JSON metadata blob (key_prefix b"t:")
  Box name: b"t:" + sha256(task_content)  →  34 bytes (well under 64-byte limit)

Methods:
  submit_task(task_hash_key, task_hash_str, task_id, author, metadata_json) -> None
  get_task(task_hash_key) -> bytes
  task_exists(task_hash_key) -> bool

Unlike CaptreApp, this contract explicitly allows UpdateApplication and DeleteApplication
via @baremethod(allow_actions=...) — learned from the CaptreApp mistake that locked 25 ALGO.

Compile with (from project root — use isolation workaround):
  mkdir -p /tmp/captre_compile && \\
  cp src/captre/contract/task_app.py /tmp/captre_compile/ && \\
  algokit compile python /tmp/captre_compile/task_app.py \\
    --out-dir /tmp/captre_compile/artifacts --output-arc32 && \\
  cp /tmp/captre_compile/artifacts/* src/captre/contract/artifacts/ && \\
  rm -rf /tmp/captre_compile
"""

from algopy import ARC4Contract, BoxMap, Bytes, String, UInt64, arc4


class TaskApp(ARC4Contract):
    """
    On-chain task submission registry.

    Stores first-claim task records keyed by a SHA-256 digest of the task
    content string. Supports update and deletion so stranded ALGO can always
    be recovered.

    Attributes
    ----------
    tasks : BoxMap[Bytes, Bytes]
        Maps ``task_hash_key`` (32-byte SHA-256 digest of the task content
        string) → serialised JSON metadata blob.
        Box key prefix: ``b"t:"``. Box name is always 34 bytes.
    """

    def __init__(self) -> None:
        self.tasks = BoxMap(Bytes, Bytes, key_prefix=b"t:")

    @arc4.baremethod(allow_actions=["UpdateApplication"])
    def update(self) -> None:
        """Allow the contract creator to update the approval program."""

    @arc4.baremethod(allow_actions=["DeleteApplication"])
    def delete(self) -> None:
        """Allow the contract creator to delete the application."""

    @arc4.abimethod
    def submit_task(
        self,
        task_hash_key: Bytes,
        task_hash_str: Bytes,
        task_id: Bytes,
        author: String,
        metadata_json: Bytes,
    ) -> None:
        """
        Write a new task record. Fails if ``task_hash_key`` is already claimed.

        Parameters
        ----------
        task_hash_key : Bytes
            32-byte SHA-256 digest of the task content string. Used as the
            ``tasks`` box key. Must not already exist — aborts with
            ``ERR_ALREADY_CLAIMED`` if so.
        task_hash_str : Bytes
            The original task content hash string (UTF-8 encoded). Stored
            verbatim inside ``metadata_json``; included here for parity with
            the ``CaptreApp`` ``attest()`` signature.
        task_id : Bytes
            Server-generated UUID for this task record (UTF-8 encoded).
        author : String
            Algorand address of the payer. Stored inside ``metadata_json``;
            validated non-empty here.
        metadata_json : Bytes
            Full JSON-serialised ``TaskRecord``. Written verbatim to the
            ``tasks`` box.

        Raises
        ------
        Assert(ERR_ALREADY_CLAIMED)
            If ``task_hash_key`` already has a box in ``tasks``.
        Assert(ERR_EMPTY_HASH)
            If ``task_hash_key`` is zero-length.
        Assert(ERR_EMPTY_HASH_STR)
            If ``task_hash_str`` is zero-length.
        Assert(ERR_EMPTY_ID)
            If ``task_id`` is zero-length.
        Assert(ERR_EMPTY_AUTHOR)
            If ``author`` is zero-length.
        Assert(ERR_EMPTY_METADATA)
            If ``metadata_json`` is zero-length.
        """
        assert task_hash_key not in self.tasks, "ERR_ALREADY_CLAIMED"
        assert task_hash_key.length > UInt64(0), "ERR_EMPTY_HASH"
        assert task_hash_str.length > UInt64(0), "ERR_EMPTY_HASH_STR"
        assert task_id.length > UInt64(0), "ERR_EMPTY_ID"
        assert author.bytes.length > UInt64(0), "ERR_EMPTY_AUTHOR"
        assert metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.tasks[task_hash_key] = metadata_json

    @arc4.abimethod(readonly=True)
    def get_task(self, task_hash_key: Bytes) -> Bytes:
        """
        Read a task record by ``task_hash_key``.

        Parameters
        ----------
        task_hash_key : Bytes
            The 32-byte SHA-256 digest key to look up.

        Returns
        -------
        Bytes
            The raw JSON metadata blob stored in the box, or ``b""`` if no
            box exists for this key.
        """
        if task_hash_key in self.tasks:
            return self.tasks[task_hash_key]
        return Bytes(b"")

    @arc4.abimethod(readonly=True)
    def task_exists(self, task_hash_key: Bytes) -> bool:
        """
        Check whether a ``task_hash_key`` has already been submitted.

        Parameters
        ----------
        task_hash_key : Bytes
            The 32-byte SHA-256 digest key to check.

        Returns
        -------
        bool
            ``True`` if a box exists for this key, ``False`` otherwise.
        """
        return task_hash_key in self.tasks
