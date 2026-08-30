"""Render `docs/architecture.md` to the PDF the Mission Control upload asks for.

The submission form takes a PDF or PNG, not Markdown, and a diagram nobody can open is
an absent deliverable. This turns the source of truth into that upload instead of asking
someone to paste blocks into a web renderer the night before — so the picture the judges
receive and the picture the repository documents cannot drift apart.

    uv run --with markdown python scripts/export_architecture.py

Two external pieces, both already on this machine after `npx @mermaid-js/mermaid-cli`:
mermaid-cli turns each fenced block into an SVG, and the Chrome it vendors prints the
assembled page. Vector all the way through, so the result is small and stays readable
when a judge zooms in.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "docs" / "architecture.md"
OUTPUT = REPO / "docs" / "architecture.pdf"

MERMAID_BLOCK = re.compile(r"^```mermaid\n(.*?)^```\n", re.DOTALL | re.MULTILINE)

# Chrome is looked up where puppeteer puts it. A missing browser is reported rather than
# worked around: a silently text-only export would be a diagram deliverable with no
# diagrams in it.
CHROME_GLOBS = (
    "chrome/*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome/*/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome/*/chrome-linux64/chrome",
    "chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell",
)

STYLE = """
@page { size: A3 landscape; margin: 12mm 16mm; }
:root {
  --ink: #10151c; --muted: #5b6673; --rule: #d7dde5;
  --authority: #1d4ed8; --money: #b45309; --paper: #ffffff;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 15px/1.55 -apple-system, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1 { font-size: 40px; line-height: 1.1; margin: 0 0 10px; letter-spacing: -0.02em; }
h2 {
  font-size: 25px; margin: 0 0 6px; letter-spacing: -0.01em;
  padding-bottom: 8px; border-bottom: 2px solid var(--ink);
}
h3 { font-size: 17px; margin: 20px 0 6px; }
p { margin: 9px 0; max-width: 105ch; }
strong { font-weight: 650; }
code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  font-size: 0.88em; background: #f2f5f9; padding: 1px 5px; border-radius: 4px;
}
hr { display: none; }
table { border-collapse: collapse; margin: 12px 0; font-size: 14px; }
th, td { border: 1px solid var(--rule); padding: 6px 12px; text-align: left; vertical-align: top; }
th { background: #f2f5f9; font-weight: 650; }
blockquote {
  margin: 12px 0; padding: 2px 0 2px 16px; border-left: 3px solid var(--rule);
  color: var(--muted);
}
ul, ol { max-width: 105ch; }
section { page-break-before: always; break-before: page; }
section:first-of-type { page-break-before: auto; break-before: auto; }
.cover {
  page-break-after: always; break-after: page;
  height: 250mm; display: flex; flex-direction: column; justify-content: center;
}
.cover .kicker {
  text-transform: uppercase; letter-spacing: 0.16em; font-size: 12px;
  color: var(--muted); margin-bottom: 18px;
}
.cover .thesis {
  font-size: 27px; line-height: 1.35; max-width: 26ch; margin: 26px 0 0;
  font-weight: 600; letter-spacing: -0.01em;
}
.cover .thesis span { color: var(--muted); font-weight: 400; }
.cover footer {
  margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--rule);
  color: var(--muted); font-size: 13px;
}
figure { margin: 16px 0 0; text-align: center; }
figure svg { max-width: 100%; max-height: 205mm; height: auto; }
.legend { color: var(--muted); font-size: 13px; margin-top: 10px; }
"""

COVER = """
<div class="cover">
  <div class="kicker">NextWave Hackathon 2026 · Desafio 01 — The Buyer Who Isn&rsquo;t Human</div>
  <h1>AVAL</h1>
  <div style="font-size:22px;color:var(--muted);margin-top:-2px">
    Pagamento agêntico com mandato verificável
  </div>
  <p class="thesis">
    O LLM propõe. O núcleo determinístico dispõe.<br>
    <span>O modelo nunca está no caminho de confiança.</span>
  </p>
  <footer>
    Arquitetura em {count} diagramas &middot; gerado de <code>docs/architecture.md</code>
  </footer>
</div>
"""


def find_chrome() -> Path:
    cache = Path.home() / ".cache" / "puppeteer"
    for pattern in CHROME_GLOBS:
        for candidate in sorted(cache.glob(pattern), reverse=True):
            if candidate.is_file():
                return candidate
    raise SystemExit(
        "Chrome não encontrado em ~/.cache/puppeteer. Rode uma vez:\n"
        "  npx --yes @mermaid-js/mermaid-cli@11 --version"
    )


def render_diagrams(markdown_text: str, workdir: Path) -> str:
    """Replace every fenced mermaid block with the SVG mermaid-cli produced for it."""
    blocks = MERMAID_BLOCK.findall(markdown_text)
    if not blocks:
        raise SystemExit(f"Nenhum bloco mermaid em {SOURCE}")
    svgs: list[str] = []
    for index, block in enumerate(blocks):
        source = workdir / f"diagram-{index}.mmd"
        target = workdir / f"diagram-{index}.svg"
        source.write_text(block, encoding="utf-8")
        subprocess.run(
            [
                "npx", "--yes", "@mermaid-js/mermaid-cli@11",
                "-i", str(source), "-o", str(target),
                "-b", "transparent", "-t", "neutral", "--width", "2000",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        svg = target.read_text(encoding="utf-8")
        # Drop the XML prolog so the fragment can be inlined into HTML.
        svg = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg)
        svgs.append(f"<figure>{svg}</figure>")
        print(f"  diagrama {index + 1}/{len(blocks)} renderizado", file=sys.stderr)

    remaining = iter(svgs)
    # A placeholder survives the Markdown pass; raw SVG would be escaped by it.
    return MERMAID_BLOCK.sub(lambda _: f"\n@@DIAGRAM{next(remaining)}@@\n\n", markdown_text)


def build_html(markdown_text: str, diagram_count: int) -> str:
    import markdown as markdown_lib

    # The export note in the source file exists to tell a reader how to produce this
    # very PDF. Inside the PDF it is instructions for something already done.
    markdown_text = re.sub(
        r"^Entregável do Mission Control\..*?mermaid\.live>\.\n", "", markdown_text,
        flags=re.DOTALL | re.MULTILINE,
    )
    markdown_text = markdown_text.split("\n", 1)[1] if markdown_text.startswith("# ") else markdown_text

    diagrams: list[str] = []

    def stash(match: re.Match[str]) -> str:
        diagrams.append(match.group(1))
        return f"@@D{len(diagrams) - 1}@@"

    markdown_text = re.sub(r"@@DIAGRAM(.*?)@@", stash, markdown_text, flags=re.DOTALL)
    body = markdown_lib.markdown(markdown_text, extensions=["tables", "sane_lists"])
    for index, svg in enumerate(diagrams):
        body = body.replace(f"<p>@@D{index}@@</p>", svg).replace(f"@@D{index}@@", svg)

    # One `## ` heading per printed page: a diagram split across a page break is a
    # diagram the reader has to reassemble.
    body = re.sub(r"<h2>", "</section><section><h2>", body)
    body = body.replace("</section><section>", "<section>", 1) + "</section>"

    return (
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        "<title>AVAL — Arquitetura</title>"
        f"<style>{STYLE}</style></head><body>"
        f"{COVER.format(count=diagram_count)}{body}</body></html>"
    )


def main() -> None:
    chrome = find_chrome()
    markdown_text = SOURCE.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as raw:
        workdir = Path(raw)
        rendered = render_diagrams(markdown_text, workdir)
        html = build_html(rendered, rendered.count("@@DIAGRAM"))
        page = workdir / "architecture.html"
        page.write_text(html, encoding="utf-8")
        produced = workdir / "architecture.pdf"
        subprocess.run(
            [
                str(chrome), "--headless", "--disable-gpu", "--no-sandbox",
                "--no-pdf-header-footer", f"--print-to-pdf={produced}", page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
        shutil.copyfile(produced, OUTPUT)
    size_mb = OUTPUT.stat().st_size / 1_048_576
    print(f"{OUTPUT.relative_to(REPO)} — {size_mb:.2f} MB (limite do formulário: 25 MB)")


if __name__ == "__main__":
    main()
