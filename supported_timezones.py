"""Canonical user timezones for the dashboard profile dropdown.

Mirror of health_tracker/logic/constants.py::SUPPORTED_TIMEZONES (the bot is a
separate repo/deploy - keep the two lists in sync). The dropdown offers these
curated zones for manual selection; browser auto-detect may store ANY valid IANA
zone (validated via is_valid_timezone), since the scheduler uses whatever IANA
name is stored on the user doc.
"""

from __future__ import annotations

# Validate with pytz - the SAME library (and version, pinned in requirements) the
# bot uses to resolve timezones. Using zoneinfo/tzdata here instead would accept
# zones the bot's pytz doesn't know, which the bot would then silently fall back
# to Israel on - so the two repos must share one validity contract.
import pytz

SUPPORTED_TIMEZONES = [
    "Pacific/Pago_Pago",    # UTC-11
    "America/Los_Angeles",  # UTC-8 / -7 (DST)
    "America/New_York",     # UTC-5 / -4 (DST)
    "America/Sao_Paulo",    # UTC-3
    "UTC",                  # UTC+0
    "Europe/London",        # UTC+0 / +1 (DST)
    "Europe/Paris",         # UTC+1 / +2 (DST)
    "Asia/Jerusalem",       # UTC+2 / +3 (DST) - default
    "Asia/Dubai",           # UTC+4
    "Asia/Kolkata",         # UTC+5:30
    "Asia/Tokyo",           # UTC+9
    "Australia/Sydney",     # UTC+10 / +11 (DST)
    "Pacific/Auckland",     # UTC+12 / +13 (DST)
    "Pacific/Kiritimati",   # UTC+14
]

DEFAULT_TIMEZONE = "Asia/Jerusalem"


def is_valid_timezone(tz: str) -> bool:
    """True if tz is a timezone the BOT can resolve (pytz).

    Accepts any pytz-known IANA zone (not only SUPPORTED_TIMEZONES), so a
    browser-detected zone we don't list in the dropdown is still storable - but
    only if the bot's pytz can actually use it, so we never persist a zone that
    would silently fall back to Israel on the bot side.
    """
    if not tz or not isinstance(tz, str):
        return False
    try:
        pytz.timezone(tz)
        return True
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError, ValueError):
        return False
