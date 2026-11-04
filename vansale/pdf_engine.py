"""The engine behind "PDF same as browser print" (Vansale Settings).

The app's PDF is desk's print view printed by Chromium (`api/printing.py`).
Everything it needs on the server is set up from Vansale Settings → "Set up
PDF engine", without root and without other apps:

  * Chromium: a Chrome for Testing headless shell, downloaded into
    `<bench>/chromium/chrome-linux/headless_shell` — the layout Print
    Designer uses, so a bench with Print Designer already has it. Site config
    `chromium_binary_path` / `chromium_path` points elsewhere.
  * Fonts: print formats ask for Arial, which Linux servers do not have.
    English falls back to Liberation Sans (Arial's widths); Arabic fell back to
    DejaVu Sans, much wider, so lines wrapped where the browser print did not.
    Noto Naskh Arabic (SIL Open Font License, in `pdf_fonts/`) keeps the
    browser print's line breaks; it goes into the bench user's font folder
    with a fontconfig rule. A server that has real Arial keeps using it.
  * System libraries Chromium links against (libnss3, …) need root: the check
    lists the missing packages and the apt command.

Fonts are installed again on every migrate while the setting is on, so a
container rebuilt with an empty home folder gets them back.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import zipfile

import frappe
from frappe import _

CHROMIUM_VERSION = "133.0.6943.35"
CHROMIUM_URL = (
    "https://storage.googleapis.com/chrome-for-testing-public/{version}/linux64/"
    "chrome-headless-shell-linux64.zip"
)
FONT_FAMILY = "Noto Naskh Arabic"
FONT_FILES = ("NotoNaskhArabic-Regular.ttf", "NotoNaskhArabic-Bold.ttf", "OFL.txt")

# Debian / Ubuntu packages Chromium needs (from the build's deb.deps).
APT_PACKAGES = (
    "libnss3", "libnspr4", "libasound2", "libatk-bridge2.0-0", "libatk1.0-0", "libatspi2.0-0",
    "libgbm1", "libgtk-3-0", "libxcomposite1", "libxdamage1", "libxfixes3", "libxkbcommon0",
    "libxrandr2", "libcups2", "libdrm2", "fonts-liberation",
)
# Library a missing `ldd` entry belongs to → its package.
LIB_PACKAGES = {
    "libnss3": "libnss3", "libnssutil3": "libnss3", "libsmime3": "libnss3", "libnspr4": "libnspr4",
    "libplc4": "libnspr4", "libplds4": "libnspr4", "libasound": "libasound2",
    "libatk-1.0": "libatk1.0-0", "libatk-bridge-2.0": "libatk-bridge2.0-0", "libatspi": "libatspi2.0-0",
    "libgbm": "libgbm1", "libxkbcommon": "libxkbcommon0", "libXcomposite": "libxcomposite1",
    "libXdamage": "libxdamage1", "libXfixes": "libxfixes3", "libXrandr": "libxrandr2",
    "libcups": "libcups2", "libdrm": "libdrm2", "libgtk-3": "libgtk-3-0",
}

FONTCONFIG_RULE = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<!-- Installed by Vansale ("Set up PDF engine"). Arabic text in formats that ask
     for Arial / Helvetica / sans-serif on a server without Arial: {FONT_FAMILY},
     which keeps the browser print's line breaks, not DejaVu Sans. -->
<fontconfig>
  <!-- Real Arial first (when installed), then Arial's metric twin for Latin,
       then the Arabic font — ahead of the generic sans-serif list (DejaVu). -->
  <alias binding="strong"><family>Arial</family>
    <prefer><family>Arial</family><family>Liberation Sans</family><family>{FONT_FAMILY}</family></prefer></alias>
  <alias binding="strong"><family>Helvetica</family>
    <prefer><family>Arial</family><family>Liberation Sans</family><family>{FONT_FAMILY}</family></prefer></alias>
  <alias binding="strong"><family>sans-serif</family>
    <prefer><family>Arial</family><family>Liberation Sans</family><family>{FONT_FAMILY}</family></prefer></alias>
  <match target="pattern">
    <test name="lang" compare="contains"><string>ar</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>{FONT_FAMILY}</string></edit>
  </match>
</fontconfig>
"""


def _bench_chromium() -> str:
    return os.path.join(frappe.utils.get_bench_path(), "chromium", "chrome-linux", "headless_shell")


def chromium_path() -> str | None:
    """Chromium for printing: site config, else the bench's own."""
    configured = frappe.conf.get("chromium_binary_path") or frappe.conf.get("chromium_path")
    candidates = [configured] if configured else []
    candidates += [_bench_chromium(), os.path.join(os.path.dirname(_bench_chromium()), "chrome")]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def download_chromium() -> str:
    """Download the headless shell into <bench>/chromium (skipped if there)."""
    existing = chromium_path()
    if existing:
        return existing
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        frappe.throw(
            _("Automatic download is for Linux x86-64 servers. Install Chromium and set {0} in site config.").format(
                "chromium_binary_path"
            )
        )
    url = frappe.get_common_site_config().get("chromium_download_url") or CHROMIUM_URL.format(
        version=frappe.conf.get("vansale_chromium_version") or CHROMIUM_VERSION
    )
    target_root = os.path.dirname(os.path.dirname(_bench_chromium()))
    os.makedirs(target_root, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target_root) as tmp:
        zip_path = os.path.join(tmp, "chromium.zip")
        import requests

        with requests.get(url, stream=True, timeout=(15, 120), headers={"User-Agent": "Wget/1.21"}) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        extracted = os.path.join(tmp, "chrome-headless-shell-linux64")
        shell = os.path.join(extracted, "chrome-headless-shell")
        if not os.path.isfile(shell):
            frappe.throw(_("The Chromium download has no headless shell"))
        os.rename(shell, os.path.join(extracted, "headless_shell"))
        target = os.path.dirname(_bench_chromium())
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.move(extracted, target)
    os.chmod(_bench_chromium(), 0o755)
    return _bench_chromium()


def _font_dirs() -> tuple[str, str]:
    home = os.path.expanduser("~")
    return (
        os.path.join(home, ".local", "share", "fonts", "vansale"),
        os.path.join(home, ".config", "fontconfig", "conf.d"),
    )


def install_fonts() -> None:
    """Bundled Arabic font + fontconfig rule into the bench user's folders."""
    font_dir, conf_dir = _font_dirs()
    os.makedirs(font_dir, exist_ok=True)
    os.makedirs(conf_dir, exist_ok=True)
    source = frappe.get_app_path("vansale", "pdf_fonts")
    for name in FONT_FILES:
        shutil.copyfile(os.path.join(source, name), os.path.join(font_dir, name))
    with open(os.path.join(conf_dir, "60-vansale-pdf.conf"), "w", encoding="utf-8") as fh:
        fh.write(FONTCONFIG_RULE)
    if shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", font_dir], capture_output=True, timeout=120, check=False)


def _missing_packages(exe: str) -> list[str]:
    try:
        out = subprocess.run(["ldd", exe], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    missing = []
    for line in out.splitlines():
        if "not found" not in line:
            continue
        lib = line.split("=>")[0].strip().split(".so")[0]
        pkg = next((p for prefix, p in LIB_PACKAGES.items() if lib.startswith(prefix)), lib)
        if pkg not in missing:
            missing.append(pkg)
    return missing


def _arabic_font(exe: str | None) -> str | None:
    """The font Chromium really uses for Arabic in a format asking for Arial:
    print a line of Arabic and read the font embedded in the PDF (fontconfig's
    own answer for "Arial" is Liberation Sans, which has no Arabic letters)."""
    if not exe:
        return None
    from pypdf import PdfReader

    with tempfile.TemporaryDirectory(prefix="vansale-font-") as tmp:
        src, out = os.path.join(tmp, "t.html"), os.path.join(tmp, "t.pdf")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write('<html lang="en"><body style="font-family: Arial, sans-serif"><p>فاتورة ضريبية</p></body></html>')
        try:
            subprocess.run(
                [exe, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                 f"--user-data-dir={os.path.join(tmp, 'profile')}", f"--print-to-pdf={out}", "file://" + src],
                capture_output=True, timeout=60, check=False,
            )
            fonts = (PdfReader(out).pages[0]["/Resources"].get("/Font") or {}).values()
        except Exception:
            return None
        names = [str(f.get_object().get("/BaseFont") or "").split("+")[-1] for f in fonts]
        return next((n for n in names if n), None)


def status() -> dict:
    """What "PDF same as browser print" has on this server."""
    exe = chromium_path()
    missing = _missing_packages(exe) if exe else []
    runs = False
    if exe and not missing:
        try:
            runs = (
                subprocess.run(
                    [exe, "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom", "about:blank"],
                    capture_output=True, timeout=30,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            runs = False
    font = _arabic_font(exe) if runs else None
    return {
        "chromium": exe,
        "chromium_runs": runs,
        "missing_packages": missing,
        "apt_command": "sudo apt-get update && sudo apt-get install -y " + " ".join(APT_PACKAGES),
        "arabic_font": font,
        # DejaVu Sans is the stock fallback: much wider than the browser's Arial.
        "arabic_font_ok": bool(font) and not font.startswith("DejaVu"),
        "ready": bool(exe) and runs and bool(font) and not font.startswith("DejaVu"),
    }


def _status_html(s: dict) -> str:
    esc = frappe.utils.escape_html

    def row(ok: bool, label: str, detail: str) -> str:
        mark = "✅" if ok else "❌"
        return f"<tr><td>{mark}</td><td><b>{esc(label)}</b></td><td>{detail}</td></tr>"

    rows = [
        row(bool(s["chromium"]), _("Chromium"), esc(s["chromium"] or _("Not installed — click Set up PDF engine"))),
        row(
            s["chromium_runs"],
            _("Chromium starts"),
            _("Yes")
            if s["chromium_runs"]
            else (
                _("Missing system packages: {0}").format(esc(", ".join(s["missing_packages"])))
                + f"<br><code>{esc(s['apt_command'])}</code>"
                if s["missing_packages"]
                else _("No")
            ),
        ),
        row(
            s["arabic_font_ok"],
            _("Arabic font"),
            esc(s["arabic_font"] or _("Unknown (Chromium not running)"))
            + ("" if s["arabic_font_ok"] else " — " + _("click Set up PDF engine")),
        ),
    ]
    head = _("Ready: the app's PDF prints like the browser.") if s["ready"] else _(
        "Not ready: the app uses Frappe's PDF until this is fixed."
    )
    return f"<p>{head}</p><table class='table table-bordered'>{''.join(rows)}</table>"


@frappe.whitelist()
def check() -> dict:
    frappe.only_for("System Manager")
    s = status()
    return {"status": s, "html": _status_html(s)}


@frappe.whitelist()
def setup() -> str:
    """Download Chromium (if needed) and install the fonts, in the background
    (the download is about 100 MB); the result is shown when it finishes."""
    frappe.only_for("System Manager")
    frappe.enqueue(
        "vansale.pdf_engine.run_setup", queue="long", timeout=1200, user=frappe.session.user
    )
    return _("Setting up the PDF engine — a notice shows when it finishes (up to a few minutes).")


def run_setup(user: str | None = None) -> dict:
    error = None
    try:
        download_chromium()
        install_fonts()
    except Exception as exc:
        error = str(exc)
        frappe.log_error(frappe.get_traceback(), "Vansale PDF engine setup")
    s = status()
    if user:
        # A short notice only (a msgprint joins whatever dialog is open);
        # the details are under "Check PDF setup".
        frappe.publish_realtime(
            "vansale_pdf_setup",
            {
                "ready": s["ready"],
                "message": _("PDF engine ready: the app's PDF prints like the browser.")
                if s["ready"]
                else (error or _("PDF engine not ready — click Check PDF setup for details.")),
            },
            user=user,
        )
    return s


def after_migrate() -> None:
    """Fonts again on every migrate (a rebuilt container loses the home
    folder), while the browser-print PDF is in use."""
    try:
        from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

        if global_flags().get("pdf_like_browser_print"):
            install_fonts()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Vansale PDF fonts")
