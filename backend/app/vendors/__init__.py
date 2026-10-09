from app.vendors.base import ParserRegistry
from app.vendors.dahua_dhav import DhavParser
from app.vendors.hikvision_fs import HikvisionFsParser
from app.vendors.honeywell_fs import HoneywellFsParser

# Tier B (documented signature + generic carving): Hikvision, Dahua, Honeywell.
# Tier C: no public byte-level signature, so no parser; carved generically and left unattributed.
# The OEM registry (app/oem/registry.json) must agree with this list (tests/test_oem_registry.py).
TIER_C_VENDORS = (
    "CP Plus",
    "Uniview",
    "TP-Link",
    "Godrej",
    "Matrix",
    "Axis",
    "Bosch",
    "Hanwha Vision",
    "VIVOTEK",
    "Avigilon",
    "Pelco",
    "Tiandy",
    "Reolink",
)


def default_registry() -> ParserRegistry:
    return ParserRegistry([HikvisionFsParser(), DhavParser(), HoneywellFsParser()])
