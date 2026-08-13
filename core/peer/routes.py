"""The paths and headers both halves of the link name."""

from protocol.version import PEER_PROTOCOL_VERSION

ROOT = f"/peer/{PEER_PROTOCOL_VERSION}"

SONGS = f"{ROOT}/songs"
PLAYLISTS = f"{ROOT}/playlists"
TRACK = f"{ROOT}/track"
PAIR_BEGIN = f"{ROOT}/pair/begin"
PAIR_PROVE = f"{ROOT}/pair/prove"

DIGEST_HEADER = "X-DeltaMusic-Digest"
