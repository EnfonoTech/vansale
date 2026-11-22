"""What the sign-in screen shows before anyone is logged in: the app's name,
its logo and the look of the screen, all from Vansale Settings.

  app_name   "App name" (the same value the installed app is named by)
  logo_url   "Login logo", else "App icon"; only a public file (a private file
             cannot be fetched before signing in)
  style      "Login style" as classic / split / dark
"""

from __future__ import annotations

from vansale import pwa

STYLES = {"Classic": "classic", "Split": "split", "Dark glass": "dark"}
DEFAULT_STYLE = "classic"


def _public(url: str | None) -> str:
    url = (url or "").strip()
    return "" if not url or url.startswith("/private/") else url


def get_branding() -> dict[str, str]:
    """The `{app_name, logo_url, style}` the app asks for on its sign-in screen.

    Empty strings when nothing is set; the app then uses its own build title and
    mark. An unknown style is `classic`.
    """
    settings = pwa._settings()
    logo = _public(settings.get("login_logo")) or _public(settings.get("pwa_icon"))
    return {
        "app_name": (settings.get("pwa_app_name") or "").strip(),
        "logo_url": logo,
        "style": STYLES.get(settings.get("login_style") or "", DEFAULT_STYLE),
    }
