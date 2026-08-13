import ssl

from core.peer.authority import authority_pem
from core.peer.identity import CoreIdentity


def server_context(identity: CoreIdentity) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=authority_pem())
    context.verify_mode = ssl.CERT_OPTIONAL
    context.load_cert_chain(str(identity.certificate_path), str(identity.key_path))
    return context


def client_context(identity: CoreIdentity) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # A core is named by its fingerprint, and the address it happens to answer at names nothing.
    context.check_hostname = False
    context.load_verify_locations(cadata=authority_pem())
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(str(identity.certificate_path), str(identity.key_path))
    return context
