"""Data-origin wording and detection of generated reference images by their 256-byte banner.

User-facing wording: the generated images are called "Reference test data" (validation documents
say "synthetic"). The machine-readable marker inside every image keeps its original text on
purpose: it is a safety marker and must keep saying SYNTHETIC / NOT REAL DVR DATA.

Every image built by the validation harness (app/validation/image.py) starts with this banner. An
acquired image that starts with it is flagged `Evidence.synthetic` so the UI can show a persistent
"SYNTHETIC - not real DVR data" banner. The check is a byte comparison of the first 256 bytes of
the stored copy; it says nothing about images without the banner (real or not).
"""

from pathlib import Path

# Keep in sync with frontend/src/dataOrigin.ts (tests/test_data_origin.py compares them).
ORIGIN_LABEL = "Reference test data"
ORIGIN_DEFINITION = (
    "built from published research and open-source format documentation, with known ground truth"
)
ORIGIN_DISCLOSURE = "Not captured from a physical DVR."
ORIGIN_HEADLINE = f"{ORIGIN_LABEL}: {ORIGIN_DEFINITION}"
TIER_LIMIT = (
    "Tier limit: no vendor is supported above Tier B, "
    "and nothing here has been validated on a real device."
)

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
