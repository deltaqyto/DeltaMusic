"""The authority every core issues its certificate under.

Its private half is a constant here, so anyone can mint a certificate that chains to it and holding one proves nothing.
It exists because a TLS stack will not hand the application a peer certificate until the chain verifies, and trust is
settled afterwards, on the fingerprint.
"""

from datetime import datetime, timezone
from functools import cache

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

AUTHORITY_SCALAR = 0x4B6F7D2A91C05E38BD47A1F6032C8E59D1B7A04E6C25F893AB0D17E42F5C9836
SERIAL = 1
SUBJECT = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DeltaMusic Peer Authority")])
NOT_BEFORE = datetime(2020, 1, 1, tzinfo=timezone.utc)
NOT_AFTER = datetime(2100, 1, 1, tzinfo=timezone.utc)


@cache
def authority_key() -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(AUTHORITY_SCALAR, ec.SECP256R1())


@cache
def authority_pem() -> str:
    """The authority certificate, for a trust store. Every core builds this one, since only the key has to be shared."""
    certificate = (
        x509.CertificateBuilder()
        .subject_name(SUBJECT)
        .issuer_name(SUBJECT)
        .public_key(authority_key().public_key())
        .serial_number(SERIAL)
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(authority_key(), hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
