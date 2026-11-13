"""Les contrôles de licence sont dispersés exprès (docs/LICENSING.md) : ce test garde chacun d'eux en place.

Il lit le code source (sans l'exécuter) : si quelqu'un déplace ou supprime un `licensing.require()`, il échoue et nomme la fonction.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "imagevers3d"

# (fichier, classe ou None, fonction) -> le contrôle doit figurer parmi les premières instructions (après la docstring)
EARLY = [
    ("image_to_3d.py", None, "load_model"),
    ("image_to_3d.py", None, "preprocess"),
    ("image_to_3d.py", None, "cutout"),
    ("image_to_3d.py", None, "generate_mesh"),
    ("image_to_3d.py", None, "export_mesh"),
    ("image_to_3d.py", None, "convert_image"),
    ("studio.py", "Engine", "preprocess"),
    ("studio.py", "Engine", "prepare_triposg"),
    ("studio.py", "Engine", "generate"),
    ("studio.py", "Engine", "generate_triposg"),
    ("studio.py", "Engine", "export_triposg"),
    ("studio.py", "Engine", "export"),
]
# Fonctions où le contrôle peut se trouver plus loin (boucle sur les images, garde avant de lancer une tâche)
ANYWHERE = [("image_to_3d.py", None, "main"), ("studio.py", "MainWindow", "run_task")]


def find_function(tree: ast.Module, cls: str | None, name: str) -> ast.FunctionDef:
    scope = tree.body
    if cls:
        scope = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls).body
    return next(node for node in scope if isinstance(node, ast.FunctionDef) and node.name == name)


def is_require_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "require"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "licensing"
    )


def body_without_docstring(function: ast.FunctionDef) -> list[ast.stmt]:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


@pytest.mark.parametrize("filename, cls, name", EARLY)
def test_check_is_among_the_first_statements(filename, cls, name):
    tree = ast.parse((SRC / filename).read_text(encoding="utf-8"))
    function = find_function(tree, cls, name)
    first = body_without_docstring(function)[:3]
    assert any(is_require_call(call) for stmt in first for call in ast.walk(stmt)), f"{cls + '.' if cls else ''}{name} ne vérifie plus la licence"


@pytest.mark.parametrize("filename, cls, name", ANYWHERE)
def test_check_is_present(filename, cls, name):
    tree = ast.parse((SRC / filename).read_text(encoding="utf-8"))
    function = find_function(tree, cls, name)
    assert any(is_require_call(node) for node in ast.walk(function)), f"{cls + '.' if cls else ''}{name} ne vérifie plus la licence"


def test_window_rechecks_periodically_and_blocks_drops():
    text = (SRC / "studio.py").read_text(encoding="utf-8")
    assert "LICENSE_CHECK_MS" in text and "_license_timer" in text
    assert "_gate_visible" in text
