import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from core.peer.authority import SUBJECT as AUTHORITY_SUBJECT, authority_key
from core.peer.keys import digest_of, spki_of
from core.peer.types.presented_core import PresentedCore

log = logging.getLogger(__name__)

KEY_FILE = "core.key"
CERTIFICATE_FILE = "core.crt"

CERTIFICATE_LIFETIME = timedelta(days=3653)
BACKDATE = timedelta(days=1)

_LEAF_KEY_USAGE = x509.KeyUsage(
    digital_signature=True,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=False,
    crl_sign=False,
    encipher_only=False,
    decipher_only=False,
)


class CoreIdentity:
    """The keypair, the certificate carrying this core's uuid and display name, and the fingerprint both ends pin on."""

    def __init__(self, config_dir: Path, display_name: str):
        self._key_path = config_dir / KEY_FILE
        self._certificate_path = config_dir / CERTIFICATE_FILE

        self._name = display_name
        self._private_key = self._load_key() or self._mint_key()
        self._fingerprint_bytes = digest_of(self._private_key.public_key())
        self._fingerprint = self._fingerprint_bytes.hex()

        held = self._load_certificate()
        self._uuid = (uuid_in(held) if held is not None else None) or str(uuid4())
        self._certificate = held if held is not None and self._describes_us(held) else self._issue()

    # Identity

    @property
    def uuid(self) -> str:
        return self._uuid

    @property
    def name(self) -> str:
        return self._name

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def fingerprint_bytes(self) -> bytes:
        return self._fingerprint_bytes

    @property
    def key_path(self) -> Path:
        return self._key_path

    @property
    def certificate_path(self) -> Path:
        return self._certificate_path

    # Internals

    def _load_key(self) -> ec.EllipticCurvePrivateKey | None:
        if not self._key_path.exists():
            return None
        try:
            key = serialization.load_pem_private_key(self._key_path.read_bytes(), password=None)
        except (OSError, TypeError, ValueError) as failure:
            # Minting another key would mint another identity, and every peer holding this one would stop trusting it.
            raise RuntimeError(f"{self._key_path} could not be read: {failure}") from failure
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise RuntimeError(f"{self._key_path} is not an EC private key")
        return key

    def _mint_key(self) -> ec.EllipticCurvePrivateKey:
        key = ec.generate_private_key(ec.SECP256R1())
        self._key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        log.info("minted a core identity in %s", self._key_path)
        return key

    def _load_certificate(self) -> x509.Certificate | None:
        if not self._certificate_path.exists():
            return None
        try:
            certificate = x509.load_pem_x509_certificate(self._certificate_path.read_bytes())
        except (OSError, ValueError) as failure:
            log.warning("could not read %s: %s", self._certificate_path, failure)
            return None
        if spki_of(certificate.public_key()) != spki_of(self._private_key.public_key()):
            log.warning("%s was issued over another key", self._certificate_path)
            return None
        return certificate

    def _describes_us(self, certificate: x509.Certificate) -> bool:
        return (
            name_in(certificate) == self._name
            and uuid_in(certificate) == self._uuid
            and certificate.issuer == AUTHORITY_SUBJECT
            and certificate.not_valid_after_utc > datetime.now(timezone.utc)
        )

    def _issue(self) -> x509.Certificate:
        """Writes a certificate over the existing keypair, which a rename is what asks for."""
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, self._name),
                x509.NameAttribute(NameOID.USER_ID, self._uuid),
            ]
        )
        moment = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(AUTHORITY_SUBJECT)
            .public_key(self._private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(moment - BACKDATE)
            .not_valid_after(moment + CERTIFICATE_LIFETIME)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_LEAF_KEY_USAGE, critical=True)
            # A core is both ends of the link.
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=False,
            )
            .sign(authority_key(), hashes.SHA256())
        )
        self._certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        return certificate


def uuid_in(certificate: x509.Certificate) -> str | None:
    attributes = certificate.subject.get_attributes_for_oid(NameOID.USER_ID)
    return str(attributes[0].value) if attributes else None


def name_in(certificate: x509.Certificate) -> str:
    attributes = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return str(attributes[0].value) if attributes else ""


def fingerprint_in(certificate_der: bytes) -> str | None:
    """The hex fingerprint of a presented certificate, which is what a peer record pins."""
    try:
        return digest_of(x509.load_der_x509_certificate(certificate_der).public_key()).hex()
    except ValueError as failure:
        log.warning("could not read a presented certificate: %s", failure)
        return None


def presented_core(certificate_der: bytes) -> PresentedCore | None:
    """Who a presented certificate claims to be, and the fingerprint the handshake proved possession of."""
    try:
        certificate = x509.load_der_x509_certificate(certificate_der)
    except ValueError as failure:
        log.warning("could not read a presented certificate: %s", failure)
        return None
    fingerprint = digest_of(certificate.public_key()).hex()
    return PresentedCore(id=uuid_in(certificate) or fingerprint, name=name_in(certificate) or fingerprint[:8], fingerprint=fingerprint)
