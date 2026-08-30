"""Print `docs/architecture.html` to the PDF the Mission Control upload asks for.

    uv run python scripts/export_architecture.py

The submission form takes a PDF or PNG, not HTML, and a diagram nobody can open is an
absent deliverable. The page is the source: it is authored for A3 landscape, every
diagram is hand-drawn inline SVG, and printing it is the only step. Nothing is redrawn
by hand for the upload, so the file the judges receive cannot drift from the file the
repository versions.

Chrome comes from the puppeteer cache that `npx @mermaid-js/mermaid-cli` populates; any
Chrome or Chromium on PATH works too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "docs" / "architecture.html"
OUTPUT = REPO / "docs" / "architecture.pdf"

CACHED_CHROME = (
    "chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome/*/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome/*/chrome-linux64/chrome",
)
INSTALLED_CHROME = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def find_chrome() -> Path:
    cache = Path.home() / ".cache" / "puppeteer"
    for pattern in CACHED_CHROME:
        for candidate in sorted(cache.glob(pattern), reverse=True):
            if candidate.is_file():
                return candidate
    for path in INSTALLED_CHROME:
        if Path(path).is_file():
            return Path(path)
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit(
        "Chrome não encontrado. Instale um, ou popule o cache do puppeteer com:\n"
        "  npx --yes @mermaid-js/mermaid-cli@11 --version"
    )


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"{SOURCE} não existe")
    chrome = find_chrome()
    result = subprocess.run(
        [
            str(chrome), "--headless", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer",
            # The page pulls its typefaces from the network. Give them time to arrive:
            # printing before they land silently falls back and changes every line break.
            "--virtual-time-budget=8000",
            f"--print-to-pdf={OUTPUT}", SOURCE.as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not OUTPUT.is_file():
        sys.stderr.write(result.stderr)
        raise SystemExit("Chrome não conseguiu imprimir a página")
    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"{OUTPUT.relative_to(REPO)} — {size_mb:.2f} MB (limite do formulário: 25 MB)")


if __name__ == "__main__":
    main()
