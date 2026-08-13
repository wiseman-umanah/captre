"""
shared/hashing.py — Deterministic SHA-256 content hashing.

Every piece of content an agent produces is hashed with this module
before being attested. The format "sha256:<hex>" is what Captre stores
as the box key.
"""

from __future__ import annotations

import hashlib


def sha256(content: str) -> str:
    """
    Compute the SHA-256 hash of a UTF-8 string and return the prefixed form.

    Parameters
    ----------
    content : str
        The text content to hash (agent output, code snippet, decision log, …).

    Returns
    -------
    str
        Hash in the form ``sha256:<64-char hex>``.
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
