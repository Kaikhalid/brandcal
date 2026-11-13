"""Run axe-core inside a Playwright page, from the copy installed in web/node_modules.

axe is injected with ``page.evaluate`` (not a <script> tag), so it works under the page's
Content-Security-Policy without loosening it. Tests skip when ``axe.min.js`` is missing
(run ``npm ci`` in web/ to get it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

AXE = Path(__file__).resolve().parents[2] / "web" / "node_modules" / "axe-core" / "axe.min.js"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

_RUN = """
async (tags) => {
  const result = await axe.run(document, { runOnly: { type: 'tag', values: tags } });
  const brief = (items) => items.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    count: v.nodes.length,
    targets: v.nodes.slice(0, 5).map((n) => n.target.join(' ')),
  }));
  return { violations: brief(result.violations), incomplete: brief(result.incomplete) };
}
"""


def axe_available() -> bool:
    return AXE.is_file()


def run_axe(page: Any) -> dict[str, list[dict[str, Any]]]:
    """Violations and incomplete checks for the page as rendered now."""
    page.evaluate(AXE.read_text(encoding="utf-8"))
    result: dict[str, list[dict[str, Any]]] = page.evaluate(_RUN, TAGS)
    return result
