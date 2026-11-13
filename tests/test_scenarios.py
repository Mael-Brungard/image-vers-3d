"""Lance les scénarios de bout en bout (un processus par scénario). Ils s'exécutent aussi à la main :
    python tests/scenarios/<nom>.py"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCENARIOS = Path(__file__).parent / "scenarios"
NEEDS = {
    "studio_ui": ("PySide6", "pyqtgraph", "OpenGL", "trimesh", "PIL", "numpy"),
    "mesh_tools": ("trimesh", "numpy", "fast_simplification", "scipy", "PIL"),
    "orientation": ("trimesh", "numpy"),
    "triposg_worker": ("trimesh", "numpy", "fast_simplification", "scipy", "skimage", "PIL"),
    "triposg_runner": ("PIL", "numpy"),
    "pythonw_no_console": ("PySide6", "pyqtgraph", "OpenGL", "trimesh", "PIL", "numpy"),
}


def missing(modules):
    import importlib.util

    return [m for m in modules if importlib.util.find_spec(m) is None]


@pytest.mark.parametrize("name", sorted(NEEDS))
def test_scenario(name):
    absent = missing(NEEDS[name])
    if absent:
        pytest.skip("modules absents : " + ", ".join(absent))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCENARIOS / f"{name}.py")],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    assert result.returncode == 0, result.stdout[-3000:] + "\n" + result.stderr[-1500:]
