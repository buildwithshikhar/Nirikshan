from app.vendors.base import ParserRegistry
from app.vendors.dahua_dhav import DhavParser
from app.vendors.hikvision import HikvisionParser
from app.vendors.honeywell import HoneywellParser

# Tier B (documented signature + generic carving). CP Plus, Uniview, TP-Link, Godrej and Matrix
# are Tier C: no public signature, so no parser; they are carved generically and left unattributed.
TIER_C_VENDORS = ("CP Plus", "Uniview", "TP-Link", "Godrej", "Matrix")


def default_registry() -> ParserRegistry:
    return ParserRegistry([HikvisionParser(), DhavParser(), HoneywellParser()])
