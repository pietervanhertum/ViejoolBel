#!/usr/bin/env python3
"""Render the printable Dutch guides (docs/PRINT-*.md) to A4 PDFs in docs/print/.

Requires ``markdown`` and ``playwright`` (with a Chromium build). Run from the
repo root:  ``python scripts/generate_print_pdfs.py``
"""

from __future__ import annotations

import glob
import pathlib

import markdown
from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
OUT = DOCS / "print"

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font: 12pt/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #16202b; }
h1 { font-size: 22pt; color: #1d4ed8; border-bottom: 3px solid #1d4ed8;
     padding-bottom: 6px; margin: 0 0 6px; }
h2 { font-size: 15pt; margin: 20px 0 6px; color: #0f2740;
     border-bottom: 1px solid #d5dde5; padding-bottom: 3px; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 14px 0 4px; }
em { color: #5a6875; }
code { background: #eef2f7; padding: 1px 5px; border-radius: 4px;
       font-family: "SFMono-Regular", Consolas, monospace; font-size: 10.5pt; }
pre { background: #0f2740; color: #e7eef7; padding: 10px 12px; border-radius: 8px;
      overflow-x: auto; font-size: 10pt; }
pre code { background: none; color: inherit; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 11pt; }
th, td { border: 1px solid #cfd8e3; padding: 6px 9px; text-align: left; vertical-align: top; }
th { background: #eef2f7; }
blockquote { border-left: 4px solid #f59e0b; background: #fffbeb; margin: 10px 0;
             padding: 8px 12px; color: #7c5307; border-radius: 0 6px 6px 0; }
ul, ol { margin: 6px 0 6px 4px; padding-left: 22px; }
li { margin: 3px 0; }
tr, li, pre, blockquote { page-break-inside: avoid; }
"""

FILES = {
    "PRINT-installatie.md": "ViejoolBel-Installatiegids.pdf",
    "PRINT-handleiding.md": "ViejoolBel-Gebruikershandleiding.pdf",
}


def _chromium_path() -> str | None:
    matches = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return matches[-1] if matches else None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    exe = _chromium_path()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page()
        for md_name, pdf_name in FILES.items():
            md_text = (DOCS / md_name).read_text(encoding="utf-8")
            body = markdown.markdown(
                md_text, extensions=["tables", "fenced_code", "sane_lists"]
            )
            html = (
                f"<!doctype html><html lang=nl><head><meta charset=utf-8>"
                f"<style>{CSS}</style></head><body>{body}</body></html>"
            )
            page.set_content(html, wait_until="networkidle")
            page.pdf(path=str(OUT / pdf_name), format="A4", print_background=True)
            print("wrote", OUT / pdf_name)
        browser.close()


if __name__ == "__main__":
    main()
