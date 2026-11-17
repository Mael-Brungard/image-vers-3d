"""Garde-fous de licence : le détourage ne doit jamais dépendre du modèle par défaut de rembg
(RMBG-2.0 / bria-rmbg : non commercial), et aucun composant exclu ne doit entrer dans les dépendances."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "threerex"

FORBIDDEN_DEPENDENCIES = ("pymeshlab", "hunyuan", "imageio-ffmpeg", "imageio[ffmpeg]", "bria", "flux")


def python_sources():
    return sorted(SRC.glob("*.py"))


def test_single_rembg_session_with_named_model():
    calls = []
    for f in python_sources():
        for number, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "new_session(" in line and not line.lstrip().startswith(("def ", "#")):
                calls.append((f.name, number, line.strip()))
    assert len(calls) == 1, calls
    assert "REMBG_MODEL" in calls[0][2]


def test_rembg_model_is_pinned_to_u2net():
    source = (SRC / "image_to_3d.py").read_text(encoding="utf-8")
    assert re.search(r'^REMBG_MODEL = "u2net"$', source, re.M)


def test_no_rembg_remove_without_session():
    for f in python_sources():
        assert "rembg.remove(" not in f.read_text(encoding="utf-8"), f.name


def test_forbidden_components_not_declared():
    declared = []
    for f in [REPO / "pyproject.toml", *(REPO / "requirements").glob("*.in")]:
        if f.exists():
            declared += [line for line in f.read_text(encoding="utf-8").lower().splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(declared)
    for name in FORBIDDEN_DEPENDENCIES:
        assert name not in text, f"composant exclu déclaré : {name}"


def test_notices_have_no_placeholders():
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "__" not in notices
    assert "U²-Net" in notices
