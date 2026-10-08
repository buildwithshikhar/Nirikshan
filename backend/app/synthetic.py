"""Detection of SYNTHETIC images by their 256-byte banner.

Every image built by the validation harness (app/validation/image.py) starts with this banner. An
acquired image that starts with it is flagged `Evidence.synthetic` so the UI can show a persistent
"SYNTHETIC - not real DVR data" banner. The check is a byte comparison of the first 256 bytes of
the stored copy; it says nothing about images without the banner (real or not).
"""

from pathlib import Path

BANNER_TEXT = (
    b"NIRIKSHAN SYNTHETIC TEST IMAGE - NOT REAL DVR DATA - generated for pipeline validation. "
)
BANNER = BANNER_TEXT.ljust(256, b" ")


def has_banner(head: bytes) -> bool:
    return head[:256] == BANNER


def is_synthetic_image(path: str | Path) -> bool:
    """True if the file starts with the full 256-byte SYNTHETIC banner. Never raises on I/O."""
    try:
        with open(path, "rb") as f:
            return has_banner(f.read(256))
    except OSError:
        return False
