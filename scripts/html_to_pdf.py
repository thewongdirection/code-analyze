#!/usr/bin/env python3
"""
html_to_pdf.py — render the code-analyze HTML dashboard to PDF.

The dashboard is authored once as a self-contained HTML file; this converts that
exact file to PDF so the two never drift. It tries, in order:
  1. A headless Chrome / Edge / Chromium via `--print-to-pdf` (best fidelity,
     honours the template's @media print styles).
  2. weasyprint, if the `weasyprint` Python package is installed.
If neither is available it prints instructions and exits non-zero, so the caller
can fall back to "open the HTML and Print → Save as PDF" rather than fabricate a PDF.

Usage:
    python html_to_pdf.py <input.html> [output.pdf]

If output is omitted it is the input path with a .pdf extension.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_browser():
    """Return a path to a Chromium-family browser, or None."""
    # Names on PATH first.
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome", "msedge", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    # Common Windows install locations (not always on PATH).
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        # Common macOS locations.
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _via_browser(browser, in_html, out_pdf):
    # A fresh temp profile avoids clobbering the user's real browser session.
    with tempfile.TemporaryDirectory(prefix="ca_pdf_") as profile:
        url = Path(in_html).resolve().as_uri()
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={os.path.abspath(out_pdf)}",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0:
            return True
        # Older builds reject --headless=new; retry with legacy flag.
        cmd[1] = "--headless"
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0


def _via_weasyprint(in_html, out_pdf):
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return False
    HTML(filename=in_html).write_pdf(out_pdf)
    return os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0


def main():
    if len(sys.argv) < 2:
        print("usage: html_to_pdf.py <input.html> [output.pdf]", file=sys.stderr)
        return 2
    in_html = sys.argv[1]
    if not os.path.isfile(in_html):
        print(f"error: input not found: {in_html}", file=sys.stderr)
        return 2
    out_pdf = sys.argv[2] if len(sys.argv) > 2 else str(Path(in_html).with_suffix(".pdf"))

    browser = _find_browser()
    if browser:
        try:
            if _via_browser(browser, in_html, out_pdf):
                print(f"PDF written via {os.path.basename(browser)}: {out_pdf}")
                return 0
        except Exception as e:
            print(f"warning: browser render failed ({e}); trying weasyprint…", file=sys.stderr)

    try:
        if _via_weasyprint(in_html, out_pdf):
            print(f"PDF written via weasyprint: {out_pdf}")
            return 0
    except Exception as e:
        print(f"warning: weasyprint failed ({e})", file=sys.stderr)

    print(
        "error: no PDF backend available.\n"
        "  Install one of: Google Chrome / Microsoft Edge / Chromium, or `pip install weasyprint`.\n"
        f"  Meanwhile, open {in_html} in a browser and use Print → Save as PDF.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
