"""UTC-ISO datetime round-trip helpers.

Every API that returns a datetime MUST pipe it through
``naive_site_to_utc_iso`` — otherwise clients in a different timezone than
the site display the wrong wall clock (fatehhr lesson #9).

Every API that accepts a client-submitted timestamp MUST parse it with
``parse_client_ts``. Frappe's ``get_datetime`` drops tzinfo on strings
ending in ``Z``; ``dateutil.isoparse`` always preserves it (fatehhr #7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import frappe
from dateutil.parser import isoparse
from frappe.utils import cint, get_datetime, get_system_timezone, now_datetime

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


# How long work done offline keeps the time it was done (site config
# `vansale_offline_grace_hours`). Older, it is dated when it reaches the server.
OFFLINE_GRACE_HOURS = 24


def document_datetime(posting_ts: Optional[str]) -> datetime:
    """Posting date/time for an invoice, payment or return the app sends.

    The app sends a time only for work queued offline (online saves send
    none), so the server's clock decides. A queued entry keeps the time it
    was done — never later than now, and only within the grace window — so
    a phone clock set back or forward cannot move a document's date (sf_trading
    measures overdue credit and cash due dates from it; ZATCA's issue date
    is it).
    """
    now = now_datetime()
    client = parse_client_ts(posting_ts) if posting_ts else None
    if client is None or client > now:
        return now
    grace = cint(frappe.conf.get("vansale_offline_grace_hours")) or OFFLINE_GRACE_HOURS
    if now - client > timedelta(hours=grace):
        return now
    return client


def naive_site_to_utc_iso(dt: Optional[Union[datetime, str]]) -> Optional[str]:
    """Convert a naive site-local datetime (or str) to a UTC ISO string with ``Z``.

    Frappe fields like ``doc.modified`` are stored as strings after insert
    / reload, so this accepts both strings and datetimes. Used on every
    outbound datetime field so device-local formatting
    (``new Date(iso).toLocaleTimeString()``) renders the correct wall
    clock regardless of where the phone is.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        # Frappe stores naive site-local strings like "2026-04-20 10:30:00".
        dt = get_datetime(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
