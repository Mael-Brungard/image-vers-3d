"""La documentation ne doit pas contenir de lien relatif cassé."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = [REPO / "README.md", REPO / "CHANGELOG.md", *sorted((REPO / "docs").glob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def heading_anchors(path: Path):
    anchors = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if match:
            slug = re.sub(r"[^\w\s-]", "", match.group(1).lower()).strip().replace(" ", "-")
            anchors.add(slug)
    return anchors


def test_relative_links_resolve():
    broken = []
    for doc in DOCS:
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, anchor = target.partition("#")
            resolved = (doc.parent / file_part).resolve() if file_part else doc
            if not resolved.exists():
                broken.append(f"{doc.name} -> {target}")
            elif anchor and resolved.suffix == ".md" and anchor not in heading_anchors(resolved):
                broken.append(f"{doc.name} -> {target} (ancre introuvable)")
    assert not broken, "\n".join(broken)
