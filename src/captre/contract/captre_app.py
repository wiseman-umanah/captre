"""
Captre smart contract — Algorand Python (AlgoKit / Puya)

Two BoxMaps:
  attestations : content_hash  → JSON metadata blob (key_prefix b"a:")
  id_index     : attestation_id → content_hash      (key_prefix b"i:")

This makes the SQLite index redundant — both lookups are fully on-chain.

Methods:
  attest(content_hash, attestation_id, author, metadata_json) -> None
  revoke(content_hash, author, updated_metadata_json) -> None
  get_attestation(content_hash) -> bytes
  resolve_id(attestation_id) -> bytes   # returns content_hash bytes, or b""
  exists(content_hash) -> bool

Compile with (from project root):
  algokit compile python src/captre/contract/captre_app.py \\
    --out-dir src/captre/contract/artifacts --output-arc32
"""

from algopy import ARC4Contract, BoxMap, Bytes, String, UInt64, arc4


class CaptreApp(ARC4Contract):
    """
    On-chain attestation registry.

    Stores first-claim attestations keyed by ``content_hash`` and provides a
    secondary index from ``attestation_id`` (UUID) to ``content_hash``.

    Attributes
    ----------
    attestations : BoxMap[Bytes, Bytes]
        Maps ``content_hash`` → serialised JSON metadata blob.
        Box key prefix: ``b"a:"``.
    id_index : BoxMap[Bytes, Bytes]
        Maps ``attestation_id`` → ``content_hash``.
        Box key prefix: ``b"i:"``.
    """

    def __init__(self) -> None:
        self.attestations = BoxMap(Bytes, Bytes, key_prefix=b"a:")
        self.id_index = BoxMap(Bytes, Bytes, key_prefix=b"i:")

    @arc4.abimethod
    def attest(
        self,
        content_hash: Bytes,
        attestation_id: Bytes,
        author: String,
        metadata_json: Bytes,
    ) -> None:
        """
        Write a new attestation. Fails if the ``content_hash`` is already claimed.

        Parameters
        ----------
        content_hash : Bytes
            SHA-256 hash of the content being attested. Used as the primary
            box key. Must not already exist in ``attestations`` —
            aborts with ``ERR_ALREADY_CLAIMED`` if so.
        attestation_id : Bytes
            Server-generated UUID for this attestation (UTF-8 encoded).
            Used as the key in ``id_index``.
        author : String
            Algorand address of the payer (from the x402 payment payload).
            Stored inside ``metadata_json``; validated non-empty here.
        metadata_json : Bytes
            Full JSON-serialised ``Attestation`` record. Written verbatim to
            the ``attestations`` box.

        Raises
        ------
        Assert(ERR_ALREADY_CLAIMED)
            If ``content_hash`` already has a box in ``attestations``.
        Assert(ERR_EMPTY_HASH)
            If ``content_hash`` is zero-length.
        Assert(ERR_EMPTY_ID)
            If ``attestation_id`` is zero-length.
        Assert(ERR_EMPTY_AUTHOR)
            If ``author`` is zero-length.
        Assert(ERR_EMPTY_METADATA)
            If ``metadata_json`` is zero-length.
        """
        assert content_hash not in self.attestations, "ERR_ALREADY_CLAIMED"
        assert content_hash.length > UInt64(0), "ERR_EMPTY_HASH"
        assert attestation_id.length > UInt64(0), "ERR_EMPTY_ID"
        assert author.bytes.length > UInt64(0), "ERR_EMPTY_AUTHOR"
        assert metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash] = metadata_json
        self.id_index[attestation_id] = content_hash

    @arc4.abimethod
    def revoke(
        self,
        content_hash: Bytes,
        author: String,
        updated_metadata_json: Bytes,
    ) -> None:
        """
        Overwrite an existing attestation box with updated (revoked) metadata.

        Parameters
        ----------
        content_hash : Bytes
            Key of the attestation box to update. Must already exist —
            aborts with ``ERR_NOT_FOUND`` if not.
        author : String
            Algorand address of the revoking payer (included for audit; not
            re-validated on-chain — authorization is enforced off-chain in
            ``revoke_attestation()`` before this call is submitted).
        updated_metadata_json : Bytes
            Updated JSON blob with ``status`` set to ``"revoked"``.

        Raises
        ------
        Assert(ERR_NOT_FOUND)
            If no box exists for ``content_hash``.
        Assert(ERR_EMPTY_METADATA)
            If ``updated_metadata_json`` is zero-length.
        """
        assert content_hash in self.attestations, "ERR_NOT_FOUND"
        assert updated_metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash] = updated_metadata_json

    @arc4.abimethod(readonly=True)
    def get_attestation(self, content_hash: Bytes) -> Bytes:
        """
        Read an attestation record by ``content_hash``.

        Parameters
        ----------
        content_hash : Bytes
            The hash to look up.

        Returns
        -------
        Bytes
            The raw JSON metadata blob stored in the box, or ``b""`` if no
            box exists for this hash.
        """
        if content_hash in self.attestations:
            return self.attestations[content_hash]
        return Bytes(b"")

    @arc4.abimethod(readonly=True)
    def resolve_id(self, attestation_id: Bytes) -> Bytes:
        """
        Resolve an ``attestation_id`` UUID to its ``content_hash``.

        Parameters
        ----------
        attestation_id : Bytes
            UTF-8 encoded UUID (e.g. ``b"a00fe88e-..."``) to look up in
            the ``id_index`` BoxMap.

        Returns
        -------
        Bytes
            The ``content_hash`` bytes stored at this UUID key, or ``b""``
            if the UUID has never been attested.
        """
        if attestation_id in self.id_index:
            return self.id_index[attestation_id]
        return Bytes(b"")

    @arc4.abimethod(readonly=True)
    def exists(self, content_hash: Bytes) -> bool:
        """
        Check whether a ``content_hash`` has already been attested.

        Parameters
        ----------
        content_hash : Bytes
            The hash to check.

        Returns
        -------
        bool
            ``True`` if a box exists for this hash, ``False`` otherwise.
        """
        return content_hash in self.attestations
