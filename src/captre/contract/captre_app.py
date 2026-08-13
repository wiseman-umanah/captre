"""
Captre smart contract — Algorand Python (AlgoKit / Puya)

Two BoxMaps:
  attestations : content_hash  → JSON metadata blob
  id_index     : attestation_id → content_hash

This makes the SQLite index redundant — both lookups are fully on-chain.

Methods:
  attest(content_hash, attestation_id, author, metadata_json) -> None
  revoke(content_hash, author, updated_metadata_json) -> None
  get_attestation(content_hash) -> bytes
  resolve_id(attestation_id) -> bytes   # returns content_hash bytes, or b""
  exists(content_hash) -> bool

Compile with (from project root):
  algokit compile python src/captre/contract/captre_app.py \
    --out-dir src/captre/contract/artifacts --output-arc32
"""

from algopy import ARC4Contract, BoxMap, Bytes, String, UInt64, arc4


class CaptreApp(ARC4Contract):

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
        assert content_hash in self.attestations, "ERR_NOT_FOUND"
        assert updated_metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash] = updated_metadata_json

    @arc4.abimethod(readonly=True)
    def get_attestation(self, content_hash: Bytes) -> Bytes:
        if content_hash in self.attestations:
            return self.attestations[content_hash]
        return Bytes(b"")

    @arc4.abimethod(readonly=True)
    def resolve_id(self, attestation_id: Bytes) -> Bytes:
        """Return the content_hash for a given attestation_id, or b"" if not found."""
        if attestation_id in self.id_index:
            return self.id_index[attestation_id]
        return Bytes(b"")

    @arc4.abimethod(readonly=True)
    def exists(self, content_hash: Bytes) -> bool:
        return content_hash in self.attestations
