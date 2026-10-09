"""Password hashing with scrypt (hashlib, OpenSSL-backed; no extra dependency).

Stored form: ``scrypt$<log2 N>$<r>$<p>$<salt b64>$<key b64>``; 16-byte random salt per hash,
32-byte derived key, comparison with hmac.compare_digest (constant time in the key bytes).
Default cost: N = 2**15, r = 8, p = 1 (about 32 MiB and roughly 50-150 ms per hash on a laptop;
measure on the deployment host). NIRIKSHAN_PASSWORD_SCRYPT_LOG2N lowers the cost for the test
suite only (minimum 10); hashes keep their own parameters, so verification is unaffected.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets

DEFAULT_LOG2N, R, P, DKLEN = 15, 8, 1, 32
MIN_LOG2N = 10
MAXMEM = 256 * 1024 * 1024
MIN_LENGTH, MAX_LENGTH = 12, 1024

log = logging.getLogger("nirikshan.auth")


class PasswordPolicyError(ValueError):
    pass


def current_log2n() -> int:
    raw = os.getenv("NIRIKSHAN_PASSWORD_SCRYPT_LOG2N", "")
    try:
        n = int(raw) if raw else DEFAULT_LOG2N
    except ValueError:
        n = DEFAULT_LOG2N
    n = max(MIN_LOG2N, min(20, n))
    if n < DEFAULT_LOG2N:
        log.warning("password scrypt cost lowered to 2**%d (tests only)", n)
    return n


def check_policy(password: str, username: str = "") -> None:
    """Length-based policy (NIST SP 800-63B style): 12..1024 characters, not the username."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_LENGTH} characters")
    if username and password.strip().lower() == username.strip().lower():
        raise PasswordPolicyError("password must not equal the username")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _derive(password: str, salt: bytes, log2n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=1 << log2n, r=r, p=p, maxmem=MAXMEM, dklen=DKLEN
    )


def hash_password(password: str) -> str:
    log2n = current_log2n()
    salt = os.urandom(16)
    return f"scrypt${log2n}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, log2n, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, log2n, r, p, salt, key = stored.split("$")
        if algo != "scrypt":
            return False
        log2n_i, r_i, p_i = int(log2n), int(r), int(p)
        if not (MIN_LOG2N <= log2n_i <= 20 and 1 <= r_i <= 32 and 1 <= p_i <= 16):
            return False
        expected = base64.b64decode(key)
        got = _derive(password, base64.b64decode(salt), log2n_i, r_i, p_i)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


_DUMMY: dict[int, str] = {}


def dummy_verify(password: str) -> None:
    """Spend the same work as a real verification (unknown usernames), to blunt timing-based
    username enumeration."""
    n = current_log2n()
    if n not in _DUMMY:
        _DUMMY[n] = hash_password(secrets.token_hex(16))  # random; matches no account
    verify_password(password, _DUMMY[n])
