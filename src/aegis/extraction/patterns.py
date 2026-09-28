"""Extraction patterns and validators (Phase 07).

Every deterministic extractor builds on this module. Validators are
real, not heuristic: Bitcoin addresses pass base58check/bech32
checksums, Ethereum addresses pass EIP-55 (keccak-256), onion v3
addresses pass their SHA3-256 checksum, and domains pass a TLD
allow-list. This is what keeps false positives out of the ledger.
"""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

_BASE32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"

# --------------------------------------------------------------- regexes

# Boundaries intentionally exclude alphanumerics so substrings of longer
# tokens (hashes, filenames, ids) are never harvested as entities.

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"(?P<local>[A-Za-z0-9._%+-]{1,64})"
    r"@"
    r"(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)"
    r"\.(?P<tld>[A-Za-z]{2,24})"
    r"(?![A-Za-z0-9-])"
)

# onion v3: 56 base32 chars + .onion (checksum verified below);
# legacy v2: 16 base32 chars + .onion (flagged, low confidence).
ONION_V3_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?P<addr>[a-z2-7]{56}\.onion)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
ONION_V2_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?P<addr>[a-z2-7]{16}\.onion)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)

WALLET_BTC_BECH32_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<addr>bc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{11,71})"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
WALLET_BTC_BASE58_RE = re.compile(
    r"(?<![0-9A-HJ-NP-Za-km-z])"
    r"(?P<addr>[13][1-9A-HJ-NP-Za-km-z]{25,34})"
    r"(?![0-9A-HJ-NP-Za-km-z])"
)
WALLET_ETH_RE = re.compile(r"(?<![A-Za-z0-9])0x(?P<addr>[0-9A-Fa-f]{40})(?![A-Za-z0-9])")

# PGP v4 fingerprints: 40 hex chars, shown grouped (10x4) or raw.
# Raw form requires non-alphanumeric boundaries so an EIP-55 address
# ("0x" + 40 hex) or a longer hex blob is never mistaken for a key.
PGP_GROUPED_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<fp>(?:[0-9A-Fa-f]{4}[ \t]){9}[0-9A-Fa-f]{4})(?![A-Za-z0-9])"
)
PGP_RAW_RE = re.compile(r"(?<![A-Za-z0-9])(?P<fp>[0-9A-Fa-f]{40})(?![A-Za-z0-9])")

DOMAIN_RE = re.compile(
    r"(?<![A-Za-z0-9.-])"
    r"(?P<domain>(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?P<tld>[A-Za-z]{2,24}))"
    r"(?![A-Za-z0-9.-])"
)

URL_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<url>(?:https?|ftp)://[^\s<>\"'\\]{4,2000}"
    r"|www\.[^\s<>\"'\\]{3,2000})"
)

HANDLE_RE = re.compile(r"(?<![\w@%+-])@(?P<handle>[A-Za-z0-9_]{2,32})(?![\w@])")

# -------------------------------------------------------- TLD allow-list

#: Practical TLD allow-list for bare-domain detection. Anything not
#: listed (``.txt``, ``.pdf``, ``.js`` — classic filename false
#: positives) only qualifies when preceded by a scheme or ``www.``.
KNOWN_TLDS = frozenset(
    """
    com net org edu gov mil int io ai app dev club co info biz mobi name pro
    ru de uk fr nl it es pt se no fi dk pl cz gr tr ua ro bg rs hr hu at ch
    be ie il in jp kr cn tw hk sg au nz za ca mx ar br cl pe
    xyz top site online club live life world today news blog wiki
    onion bazar balancer shop store market mall goods pay fund cash coin
    wallet token win bet casino poker
    cc tv me cf ga tk ml gq us ca
    eu asiajobs careers finance health tech digital systems solutions group
    """.split()
)

#: Labels that look like filenames rather than hosts when the TLD is
#: not explicitly trusted (``report.pdf``, ``notes.txt``...).
_NOT_HOST_TLDS = frozenset(
    {
        "txt",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "csv",
        "json",
        "xml",
        "yml",
        "yaml",
        "md",
        "log",
        "bak",
        "tmp",
        "swp",
        "py",
        "js",
        "ts",
        "jsx",
        "go",
        "rs",
        "java",
        "c",
        "h",
        "cpp",
        "sh",
        "bat",
        "ps1",
        "sql",
        "ini",
        "cfg",
        "conf",
        "env",
        "lock",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "mp3",
        "mp4",
        "zip",
        "tar",
        "gz",
        "rar",
        "7z",
        "iso",
        "img",
        "exe",
        "dll",
        "so",
        "deb",
        "rpm",
        "apk",
        "dmg",
        "pkg",
        "db",
        "sqlite",
        "pcap",
    }
)

# ------------------------------------------------------------- checksums

_BTC58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GEN = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
_MASK64 = (1 << 64) - 1


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def keccak256(data: bytes) -> bytes:
    """Keccak-256 (original Keccak padding 0x01, as used by Ethereum).

    Implemented directly: hashlib's ``sha3_256`` uses SHA-3 padding
    (0x06), which differs from the Keccak padding Ethereum hashes with.
    """
    rate = 136  # 1088-bit rate for Keccak-256

    state = [0] * 25

    def _permute() -> None:
        rc = (
            0x0000000000000001,
            0x0000000000008082,
            0x800000000000808A,
            0x8000000080008000,
            0x000000000000808B,
            0x0000000080000001,
            0x8000000080008081,
            0x8000000000008009,
            0x000000000000008A,
            0x0000000000000088,
            0x0000000080008009,
            0x000000008000000A,
            0x000000008000808B,
            0x800000000000008B,
            0x8000000000008089,
            0x8000000000008003,
            0x8000000000008002,
            0x8000000000000080,
            0x000000000000800A,
            0x800000008000000A,
            0x8000000080008081,
            0x8000000000008080,
            0x0000000080000001,
            0x8000000080008008,
        )
        rotations = (
            (0, 36, 3, 41, 18),
            (1, 44, 10, 45, 2),
            (62, 6, 43, 15, 61),
            (28, 55, 25, 21, 56),
            (27, 20, 39, 8, 14),
        )

        def _rotl(value: int, shift: int) -> int:
            shift %= 64
            if shift == 0:
                return value
            return ((value << shift) | (value >> (64 - shift))) & _MASK64

        for round_constant in rc:
            # theta
            c = [
                state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
                for x in range(5)
            ]
            d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    state[x + 5 * y] ^= d[x]
            # rho + pi
            b = [0] * 25
            for x in range(5):
                for y in range(5):
                    b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(state[x + 5 * y], rotations[x][y])
            # chi
            for x in range(5):
                for y in range(5):
                    state[x + 5 * y] = b[x + 5 * y] ^ (
                        (~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y]
                    )
            # iota
            state[0] ^= round_constant
            state[0] &= _MASK64
            for lane in range(1, 25):
                state[lane] &= _MASK64

    # multi-rate padding 0x01 ... 0x80
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for lane in range(rate // 8):
            value = int.from_bytes(block[lane * 8 : lane * 8 + 8], "little")
            state[lane] ^= value
        _permute()

    out = bytearray()
    for lane in range(4):  # 32 bytes
        out += state[lane].to_bytes(8, "little")
    return bytes(out)


def _bech32_polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index in range(5):
            if (top >> index) & 1:
                checksum ^= _BECH32_GEN[index]
    return checksum


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(ch) >> 5 for ch in hrp] + [0] + [ord(ch) & 31 for ch in hrp]


def is_valid_btc_bech32(address: str) -> bool:
    """Full BIP-173 validation (charset, mixed-case rule, checksum)."""
    if address != address.lower() and address != address.upper():
        return False  # mixed case is invalid per BIP-173
    lowered = address.lower()
    separator = lowered.rfind("1")
    if separator < 1 or separator + 7 > len(lowered):
        return False
    hrp, data_part = lowered[:separator], lowered[separator + 1 :]
    if hrp not in {"bc", "tb", "bcrt"}:
        return False
    if any(ch not in _BECH32_CHARSET for ch in data_part):
        return False
    data = [_BECH32_CHARSET.index(ch) for ch in data_part]
    expanded = _bech32_hrp_expand(hrp) + data
    if _bech32_polymod(expanded) != 1:
        return False
    # witness version (5 bits) + program + checksum (30 bits)
    program_bits = (len(data) - 7) * 5
    return 8 <= program_bits <= 160


def _base58_decode(value: str) -> bytes | None:
    decimal = 0
    for ch in value:
        index = _BTC58_ALPHABET.find(ch)
        if index < 0:
            return None
        decimal = decimal * 58 + index
    body = decimal.to_bytes((decimal.bit_length() + 7) // 8, "big")
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeros + body


def is_valid_btc_base58(address: str) -> bool:
    """Base58Check: decode, verify 4-byte double-SHA256 checksum."""
    if not 26 <= len(address) <= 35:
        return False
    decoded = _base58_decode(address)
    if decoded is None or len(decoded) < 5:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    return _sha256d(payload)[:4] == checksum


def eth_checksum_status(address: str) -> str:
    """EIP-55 verification (``0x`` prefix optional).

    Returns ``"checksum"`` (mixed-case, verified), ``"structural"``
    (all one case — checksum not applicable), or ``"invalid"``.
    """
    if address.lower().startswith("0x"):
        address = address[2:]
    if len(address) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in address):
        return "invalid"
    if address.islower() or address.isupper():
        return "structural"
    digest = keccak256(address.lower().encode("ascii")).hex()
    for index, char in enumerate(address):
        if char.isalpha():
            expected_upper = int(digest[index], 16) >= 8
            if char.isupper() != expected_upper:
                return "invalid"
    return "checksum"


_ONION_V3_DOMAIN = b".onion checksum"


def is_valid_onion(address: str, *, version: int) -> bool:
    """Validate an onion address.

    v3: 56 base32 chars decoding to pubkey(32)+checksum(2)+version(1)
    with SHA3-256 checksum verification. v2: length/charset only (v2
    carries no checksum).
    """
    local = address[: -len(".onion")]
    lowered = local.lower()
    if version == 2:
        return len(lowered) == 16 and all(ch in _BASE32_ALPHABET for ch in lowered)
    if len(lowered) != 56 or any(ch not in _BASE32_ALPHABET for ch in lowered):
        return False
    try:
        decoded = base64.b32decode(local.upper())
    except ValueError:
        return False
    if len(decoded) != 35:
        return False
    public_key, checksum, version_byte = decoded[:32], decoded[32:34], decoded[34]
    if version_byte != 0x03:
        return False
    expected = hashlib.sha3_256(_ONION_V3_DOMAIN + public_key + bytes([version_byte])).digest()[:2]
    return checksum == expected


# ------------------------------------------------------------ normalizers


def normalize_handle(value: str) -> str:
    return value.lstrip("@").lower()


def normalize_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


def normalize_domain(value: str) -> str:
    domain = unicodedata.normalize("NFKC", value).strip().rstrip(".").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalize_onion(value: str) -> str:
    return value.strip().lower()


def normalize_pgp(value: str) -> str:
    return re.sub(r"[\s:]", "", value).lower()


def normalize_wallet(value: str) -> str:
    """bech32/ETH are case-insensitive; base58 is not."""
    value = value.strip()
    if value.lower().startswith("bc1"):
        return value.lower()
    if value.lower().startswith("0x"):
        return "0x" + value[2:].lower()
    return value


URL_TRAILING_PUNCTUATION = ".,;:!?)]}'\"\u201d\u2019"


def normalize_url(value: str) -> str | None:
    """Canonical URL: lowercase scheme/host, drop fragment, strip
    trailing sentence punctuation. Returns None if unparseable."""
    candidate = value.strip()
    while candidate and candidate[-1] in URL_TRAILING_PUNCTUATION:
        candidate = candidate[:-1]
    if "://" not in candidate:
        if not candidate.lower().startswith("www."):
            return None
        candidate = "http://" + candidate
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if not parts.netloc:
        return None
    if parts.scheme not in {"http", "https", "ftp"}:
        return None
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",  # fragment dropped: never part of the fetched resource
        )
    )


def url_domain(value: str) -> str | None:
    """Host of a URL (None when the URL is unparseable)."""
    normalized = normalize_url(value)
    if normalized is None:
        return None
    host = urlsplit(normalized).hostname
    return host or None


def domain_looks_like_host(domain: str, preceding: str) -> bool:
    """Decide a bare domain candidate is a host, not a filename.

    Trusted when the TLD is allow-listed, or when the domain is
    introduced by a scheme/``www.`` context. ``report.pdf``-style
    candidates fail both checks.
    """
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld == "onion":
        return False  # handled (and checksummed) by the onion extractor
    if tld in _NOT_HOST_TLDS:
        return False
    if tld in KNOWN_TLDS:
        return True
    context = preceding[-8:].lower()
    return context.endswith("://") or context.endswith("www.") or context.endswith("//")
