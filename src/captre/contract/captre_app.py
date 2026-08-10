"""
Captre smart contract — Algorand Python (AlgoKit / Puya)

Box key  : content_hash bytes (up to 64 bytes)
Box value: JSON-encoded attestation record

Methods:
  attest(content_hash, author, metadata_json) -> None
  revoke(content_hash, author, updated_metadata_json) -> None
  get_attestation(content_hash) -> bytes
  exists(content_hash) -> bool

Compile with:
  algokit compile python contract/captre_app.py --out-dir src/captre/contract/artifacts --output-arc32
"""

from algopy import ARC4Contract, BoxMap, Bytes, String, UInt64, arc4


class CaptreApp(ARC4Contract):

    def __init__(self) -> None:
        self.attestations = BoxMap(Bytes, Bytes, key_prefix=b"")

    @arc4.abimethod
    def attest(
        self,
        content_hash: Bytes,
        author: String,
        metadata_json: Bytes,
    ) -> None:
        assert content_hash not in self.attestations, "ERR_ALREADY_CLAIMED"
        assert content_hash.length > UInt64(0), "ERR_EMPTY_HASH"
        assert author.bytes.length > UInt64(0), "ERR_EMPTY_AUTHOR"
        assert metadata_json.length > UInt64(0), "ERR_EMPTY_METADATA"
        self.attestations[content_hash] = metadata_json

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
    def exists(self, content_hash: Bytes) -> bool:
        return content_hash in self.attestations
