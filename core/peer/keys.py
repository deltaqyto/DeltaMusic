"""The SubjectPublicKeyInfo a core fingerprint is taken over."""

from hashlib import sha256

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def spki_of(public_key: ec.EllipticCurvePublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def digest_of(public_key: ec.EllipticCurvePublicKey) -> bytes:
    """The raw SHA-256 of the DER SubjectPublicKeyInfo, which is what a peer record pins."""
    return sha256(spki_of(public_key)).digest()
