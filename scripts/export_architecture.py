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
import tempfile
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


def print_pdf(chrome: Path, page: Path, target: Path, extra_css: str = "") -> None:
    source = page
    if extra_css:
        # A probe copy, so the real page is never edited to be measured.
        source = target.with_suffix(".probe.html")
        source.write_text(
            page.read_text(encoding="utf-8").replace(
                "</style>", f"</style>\n<style>{extra_css}</style>", 1
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            str(chrome), "--headless", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer",
            # The page pulls its typefaces from the network. Give them time to arrive:
            # printing before they land silently falls back and changes every line break.
            "--virtual-time-budget=8000",
            f"--print-to-pdf={target}", source.as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    if extra_css:
        source.unlink(missing_ok=True)
    if result.returncode != 0 or not target.is_file():
        sys.stderr.write(result.stderr)
        raise SystemExit("Chrome não conseguiu imprimir a página")


def page_count(pdf: Path) -> int:
    """Count pages without a PDF library: `/Type /Page` outside the page tree node."""
    raw = pdf.read_bytes()
    return raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")


def check_no_overflow(chrome: Path, sections: int) -> None:
    """Fail loudly when a section is taller than its sheet.

    Every section is a fixed 297mm box, so anything past that is silently *clipped* on
    print — a paragraph loses its last line and the artifact looks finished. Printing a
    second time with the height released turns that same overflow into extra pages, and
    the count is the alarm. This is the check that would have caught two cropped pages.
    """
    with tempfile.TemporaryDirectory() as raw:
        probe = Path(raw) / "probe.pdf"
        print_pdf(chrome, SOURCE, probe, "\n.page { height: auto !important; min-height: 297mm; }")
        pages = page_count(probe)
    if pages > sections:
        raise SystemExit(
            f"{pages - sections} seção(ões) passam da folha e seriam cortadas na impressão.\n"
            f"Reimprima com `.page {{ height: auto }}` e veja onde o conteúdo cai."
        )


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"{SOURCE} não existe")
    chrome = find_chrome()
    sections = SOURCE.read_text(encoding="utf-8").count('<section class="page')
    check_no_overflow(chrome, sections)
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
