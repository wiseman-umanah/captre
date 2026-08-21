"""
shared/wallet.py — Algorand wallet implementing the x402 ClientAvmSigner protocol.

Each agent holds an in-memory AlgorandWallet built from a 25-word mnemonic.
The wallet is passed to x402ClientSync via register_exact_avm_client, enabling
automatic x402 payment payload creation without touching any Captre app code.

Signing round-trip used by x402:
  ExactAvmScheme encodes each Transaction → b64str → b64decode → raw msgpack bytes
  It passes those bytes to sign_transactions(unsigned_txns, indexes_to_sign).
  We reverse: b64encode(raw) → msgpack_decode → .sign(pk) → b64decode(msgpack_encode(signed)).
"""

from __future__ import annotations

import base64
from typing import cast

from algosdk import account as algo_account
from algosdk import encoding, mnemonic
from algosdk.transaction import Transaction


class AlgorandWallet:
    """
    A thin Algorand signing wallet satisfying the x402 ClientAvmSigner protocol.

    Created from a 25-word mnemonic. Exposes the ``address`` property and the
    ``sign_transactions`` method required by ``ExactAvmScheme``.

    Attributes
    ----------
    address : str
        The 58-character Algorand address derived from the mnemonic.
    """

    def __init__(self, mnemonic_phrase: str) -> None:
        """
        Construct an AlgorandWallet from a mnemonic phrase.

        Parameters
        ----------
        mnemonic_phrase : str
            The 25-word Algorand mnemonic. Whitespace is normalised.

        Raises
        ------
        ValueError
            If the mnemonic is invalid or cannot be decoded.
        """
        self._private_key: str = mnemonic.to_private_key(mnemonic_phrase.strip())
        self.address: str = algo_account.address_from_private_key(self._private_key)

    @classmethod
    def generate(cls) -> AlgorandWallet:
        """
        Generate a brand-new random Algorand wallet.

        Returns
        -------
        AlgorandWallet
            A fresh wallet. Access wallet.mnemonic_phrase to persist it.
        """
        private_key, _address = algo_account.generate_account()
        phrase = mnemonic.from_private_key(private_key)
        return cls(phrase)

    @property
    def mnemonic_phrase(self) -> str:
        """
        Return the 25-word mnemonic for this wallet.

        Returns
        -------
        str
            Space-separated 25-word mnemonic.
        """
        return mnemonic.from_private_key(self._private_key)

    # -------------------------------------------------------------------------
    # ClientAvmSigner protocol
    # -------------------------------------------------------------------------

    def sign_transactions(
        self,
        unsigned_txns: list[bytes],
        indexes_to_sign: list[int],
    ) -> list[bytes | None]:
        """
        Sign selected transactions in a group (x402 ClientAvmSigner protocol).

        x402's ExactAvmScheme encodes each Transaction as:
            base64.b64decode(encoding.msgpack_encode(txn))   → raw msgpack bytes
        and passes those raw bytes here. We reverse the encoding to get a
        Transaction, sign it, then return raw msgpack bytes of the SignedTransaction.

        Parameters
        ----------
        unsigned_txns : list[bytes]
            Raw msgpack bytes for each transaction in the group.
        indexes_to_sign : list[int]
            Indices of transactions this wallet should sign.

        Returns
        -------
        list[bytes | None]
            Parallel list: signed raw msgpack bytes at each index in
            ``indexes_to_sign``, ``None`` everywhere else.
        """
        result: list[bytes | None] = [None] * len(unsigned_txns)
        for idx in indexes_to_sign:
            # raw bytes → b64str → Transaction object
            b64str = base64.b64encode(unsigned_txns[idx]).decode()
            txn = cast(Transaction, encoding.msgpack_decode(b64str))
            # sign and re-encode to raw bytes
            signed = txn.sign(self._private_key)
            result[idx] = base64.b64decode(encoding.msgpack_encode(signed))
        return result
