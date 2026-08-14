"""
Captre smart contract — Algorand Python (AlgoKit / Puya)

Two BoxMaps:
  attestations : content_hash_key (32-byte SHA-256 digest of content_hash string)
                   → JSON metadata blob (key_prefix b"a:")
  id_index     : attestation_id → content_hash_str (original string, key_prefix b"i:")

Box key layout:
  attestations box name: b"a:" + sha256(content_hash_string)  →  34 bytes (well under 64-byte limit)
  id_index box name:     b"i:" + attestation_id_uuid          →  38 bytes

Methods:
  attest(content_hash_key, content_hash_str, attestation_id, author, metadata_json) -> None
  revoke(content_hash_key, author, updated_metadata_json) -> None
  get_attestation(content_hash_key) -> bytes
  resolve_id(attestation_id) -> bytes   # returns content_hash_str bytes, or b""
  exists(content_hash_key) -> bool

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
        Maps ``content_hash_key`` (32-byte SHA-256 digest of the original
        content_hash string) → serialised JSON metadata blob.
        Box key prefix: ``b"a:"``. Box name is always 34 bytes.
    id_index : BoxMap[Bytes, Bytes]
        Maps ``attestation_id`` → ``content_hash_str`` (the original human-
        readable content_hash string, e.g. ``"sha256:<hex>"``).
        Box key prefix: ``b"i:"``.
    """

    def __init__(self) -> None:
        self.attestations = BoxMap(Bytes, Bytes, key_prefix=b"a:")
        self.id_index = BoxMap(Bytes, Bytes, key_prefix=b"i:")

    @arc4.abimethod
    def attest(
        self,
        content_hash_key: Bytes,
        content_hash_str: Bytes,
        attestation_id: Bytes,
        author: String,
        metadata_json: Bytes,
    ) -> None:
        """
        Write a new attestation. Fails if the ``content_hash_key`` is already claimed.

        Parameters
        ----------
        content_hash_key : Bytes
            32-byte SHA-256 digest of the original content_hash string. Used
            as the ``attestations`` box key. Must not already exist —
            aborts with ``ERR_ALREADY_CLAIMED`` if so.
        content_hash_str : Bytes
            The original content_hash string (e.g. ``b"sha256:abc123..."``),
            UTF-8 encoded. Stored in ``id_index`` so callers can recover it
            via ``resolve_id()``.
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
            If ``content_hash_key`` already has a box in ``attestations``.
        Assert(ERR_EMPTY_HASH)
            If ``content_hash_key`` is zero-length.
        Assert(ERR_EMPTY_HASH_STR)
            If ``content_hash_str`` is zero-length.
        Assert(ERR_EMPTY_ID)
            If ``attestation_id`` is zero-length.
        Assert(ERR_EMPTY_AUTHOR)
            If ``author`` is zero-length.
        Assert(ERR_EMPTY_METADATA)
            If ``metadata_json`` is zero-length.
        """
        assert content_hash_key not in self.attestations, "ERR_ALREADY_CLAIMED"
        assert content_hash_key.length > UInt64(0), "ERR_EMPTY_HASH"
        assert content_hash_str.length > UInt64(0), "ERR_EMPTY_HASH_STR"
        assert attestation_id.length > UInt64(0), "ERR_EMPTY_ID"
        assert author.bytes.length > UInt64(0), "ERR_EMPTY_AUTHOR"
        assert metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash_key] = metadata_json
        self.id_index[attestation_id] = content_hash_str

    @arc4.abimethod
    def revoke(
        self,
        content_hash_key: Bytes,
        author: String,
        updated_metadata_json: Bytes,
    ) -> None:
        """
        Overwrite an existing attestation box with updated (revoked) metadata.

        Parameters
        ----------
        content_hash_key : Bytes
            32-byte SHA-256 digest key of the attestation box to update.
            Must already exist — aborts with ``ERR_NOT_FOUND`` if not.
        author : String
            Algorand address of the revoking payer (included for audit; not
            re-validated on-chain — authorization is enforced off-chain in
            ``revoke_attestation()`` before this call is submitted).
        updated_metadata_json : Bytes
            Updated JSON blob with ``status`` set to ``"revoked"``.

        Raises
        ------
        Assert(ERR_NOT_FOUND)
            If no box exists for ``content_hash_key``.
        Assert(ERR_EMPTY_METADATA)
            If ``updated_metadata_json`` is zero-length.
        """
        assert content_hash_key in self.attestations, "ERR_NOT_FOUND"
        assert updated_metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash_key] = updated_metadata_json

    @arc4.abimethod(readonly=True)
    def get_attestation(self, content_hash_key: Bytes) -> Bytes:
        """
        Read an attestation record by ``content_hash_key``.

        Parameters
        ----------
        content_hash_key : Bytes
            The 32-byte SHA-256 digest key to look up.

        Returns
        -------
        Bytes
            The raw JSON metadata blob stored in the box, or ``b""`` if no
            box exists for this key.
        """
        if content_hash_key in self.attestations:
            return self.attestations[content_hash_key]
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
    def exists(self, content_hash_key: Bytes) -> bool:
        """
        Check whether a ``content_hash_key`` has already been attested.

        Parameters
        ----------
        content_hash_key : Bytes
            The 32-byte SHA-256 digest key to check.

        Returns
        -------
        bool
            ``True`` if a box exists for this key, ``False`` otherwise.
        """
        return content_hash_key in self.attestations
