"""Le remplaçant de torchmcubes doit respecter ses conventions (axes, sens des faces, maillage vide)."""

import math
import sys

import numpy as np
import pytest

pytest.importorskip("skimage")
trimesh = pytest.importorskip("trimesh")

from imagevers3d import mcubes_fallback  # noqa: E402


def ellipsoid_volume(n, radii):
    """Valeur positive à l'intérieur, nulle sur la surface ; axes indexés [axe0][axe1][axe2]."""
    grid = np.indices((n, n, n)).astype(np.float32)
    c = (n - 1) / 2
    d = sum(((grid[i] - c) / radii[i]) ** 2 for i in range(3))
    return (1.0 - d).astype(np.float32)


def test_sphere_area_volume_and_orientation():
    n, r = 48, 15.0
    vol = ellipsoid_volume(n, (r, r, r))
    verts, faces = mcubes_fallback.marching_cubes_numpy(vol, 0.0)
    assert verts.dtype == np.float32 and faces.dtype == np.int32
    # TripoSR remet les axes dans l'ordre d'origine (v[..., [2, 1, 0]]) : c'est dans ce repère que les faces
    # doivent regarder vers l'extérieur (volume positif).
    mesh = trimesh.Trimesh(verts[:, ::-1], faces, process=False)
    assert mesh.volume > 0, "faces tournées vers l'extérieur attendues"
    assert mesh.volume == pytest.approx(4 / 3 * math.pi * r**3, rel=0.03)
    assert mesh.area == pytest.approx(4 * math.pi * r**2, rel=0.03)


def test_axes_are_reversed_like_torchmcubes():
    n = 48
    radii = (16.0, 11.0, 7.0)  # axe0, axe1, axe2
    verts, _ = mcubes_fallback.marching_cubes_numpy(ellipsoid_volume(n, radii), 0.0)
    extent = verts.max(axis=0) - verts.min(axis=0)
    # sommets rendus dans l'ordre (axe2, axe1, axe0)
    assert extent == pytest.approx([2 * radii[2], 2 * radii[1], 2 * radii[0]], abs=1.5)


def test_empty_volume_gives_empty_mesh():
    for vol in (np.zeros((8, 8, 8), np.float32), np.full((8, 8, 8), -1.0, np.float32)):
        verts, faces = mcubes_fallback.marching_cubes_numpy(vol, 0.5)
        assert verts.shape == (0, 3) and faces.shape == (0, 3)


def test_install_registers_torchmcubes_when_missing(monkeypatch):
    def missing(name, *args, **kwargs):
        raise ImportError(name)

    monkeypatch.delitem(sys.modules, "torchmcubes", raising=False)
    monkeypatch.setattr(mcubes_fallback.importlib, "import_module", missing)
    assert mcubes_fallback.install_if_needed() is True
    module = sys.modules["torchmcubes"]
    assert module.marching_cubes is mcubes_fallback.marching_cubes
    monkeypatch.delitem(sys.modules, "torchmcubes")  # ne rien laisser derrière soi
