"""UTC-ISO datetime round-trip helpers.

Every API that returns a datetime MUST pipe it through
``naive_site_to_utc_iso`` — otherwise clients in a different timezone than
the site display the wrong wall clock (fatehhr lesson #9).

Every API that accepts a client-submitted timestamp MUST parse it with
``parse_client_ts``. Frappe's ``get_datetime`` drops tzinfo on strings
ending in ``Z``; ``dateutil.isoparse`` always preserves it (fatehhr #7).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from dateutil.parser import isoparse
from frappe.utils import get_system_timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python 3.10+ has zoneinfo
    from backports.zoneinfo import ZoneInfo  # type: ignore[assignment]


def parse_client_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse a client-submitted ISO timestamp into a naive site-local datetime.

    Accepts ``"2026-04-19T15:25:16.123Z"`` and other timezone-aware ISO
    forms. If the string has no tz, assumes UTC.
    """
    if not ts_str:
        return None
    dt = isoparse(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def naive_site_to_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert a naive site-local datetime to a UTC ISO string with ``Z``.

    Used on every outbound datetime field so device-local formatting
    (``new Date(iso).toLocaleTimeString()``) renders the correct wall
    clock regardless of where the phone is.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
