"""Préparation à l'impression 3D : réparation, échelle en millimètres, pose à plat, STL, rapport."""

import io
import math

import numpy as np
import pytest
import trimesh

from threerex import printing
from threerex.geometry import ORIENTATION, rotation


def sphere(subdivisions: int = 4, radius: float = 0.5) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


def box(x: float, y: float, z: float) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=[x, y, z])


def without(mesh: trimesh.Trimesh, mask: np.ndarray) -> trimesh.Trimesh:
    """Le même maillage privé des faces désignées par `mask` : des trous."""
    return trimesh.Trimesh(mesh.vertices, mesh.faces[~mask], process=False)


def run(mesh, height=100, flatten=True):
    return printing.make_printable(mesh, height_mm=height, flatten_base=flatten)


# ---- échelle, pose, repère -------------------------------------------------------------------------------------------
def test_closed_sphere_is_scaled_to_the_height_and_laid_flat():
    out, report = run(sphere(), 100)
    low, high = out.vertices.min(axis=0), out.vertices.max(axis=0)
    assert report.watertight and report.shells == 1 and report.holes_closed == 0
    assert low[2] == pytest.approx(0.0, abs=1e-9) and high[2] == pytest.approx(100.0)
    assert (low[0] + high[0]) / 2 == pytest.approx(0.0, abs=1e-6) and (low[1] + high[1]) / 2 == pytest.approx(0.0, abs=1e-6)
    assert report.size_mm[2] == 100.0
    radius = (high[0] - low[0]) / 2
    assert report.volume_cm3 == pytest.approx(4 / 3 * math.pi * radius ** 3 / 1000, rel=0.03)


def test_the_height_is_the_vertical_axis_of_the_export():
    """Le repère de l'export a Y vers le haut ; le fichier d'impression a Z vers le haut."""
    out, report = run(box(1, 3, 1), 90)
    assert report.size_mm == pytest.approx((30.0, 30.0, 90.0))
    assert np.ptp(out.vertices[:, 2]) == pytest.approx(90.0)


def test_scale_of_the_input_does_not_matter():
    small, _ = run(sphere(radius=0.0005), 100)
    large, _ = run(sphere(radius=500.0), 100)
    assert np.ptp(small.vertices, axis=0) == pytest.approx(np.ptp(large.vertices, axis=0), rel=1e-6)


def test_a_flat_bottom_is_left_alone():
    _, report = run(box(1, 2, 0.6), 80)
    assert report.flattened_mm == 0.0
    assert report.size_mm == pytest.approx((40.0, 24.0, 80.0))
    assert report.volume_cm3 == pytest.approx(40 * 24 * 80 / 1000)


def test_a_round_bottom_is_flattened_a_little():
    out, report = run(sphere(), 100)
    assert report.flattened_mm == pytest.approx(printing.FLATTEN_FRACTION * 100, rel=0.1)
    floor = out.vertices[out.vertices[:, 2] < 1e-6]
    assert len(floor) >= 3  # un vrai plan, pas une pointe
    _, kept = run(sphere(), 100, flatten=False)
    assert kept.flattened_mm == 0.0


# ---- réparation ------------------------------------------------------------------------------------------------------
def test_holes_are_closed():
    s = sphere()
    holey = without(s, s.triangles_center[:, 1] > 0.45)
    assert not holey.is_watertight
    _, report = run(holey)
    assert report.watertight and report.holes_closed == 1 and report.holes_left == 0
    assert report.volume_cm3 and report.volume_cm3 > 0


def test_a_missing_bottom_comes_back_flat():
    cube = box(2, 1, 2)
    open_box = without(cube, cube.triangles_center[:, 1] < -0.49)
    _, report = run(open_box, 50)
    assert report.watertight and report.holes_closed == 1
    assert report.flattened_mm == 0.0  # le fond refermé est déjà plat : rien à couper


def test_many_small_holes_are_all_closed():
    s = sphere(5)
    mask = np.random.default_rng(1).random(len(s.faces)) < 0.01
    _, report = run(without(s, mask))
    assert report.watertight and report.holes_closed >= 1 and report.holes_left == 0


def test_duplicated_vertices_are_welded():
    """Un .glb duplique les sommets le long des coutures de texture : sans soudure, chaque couture serait un « trou »."""
    s = sphere()
    soup = trimesh.Trimesh(s.vertices[s.faces].reshape(-1, 3), np.arange(len(s.faces) * 3).reshape(-1, 3), process=False)
    _, report = run(soup)
    assert report.watertight and report.shells == 1 and report.holes_closed == 0


def test_inverted_normals_give_a_positive_volume():
    s = sphere()
    _, report = run(trimesh.Trimesh(s.vertices, s.faces[:, ::-1], process=False))
    assert report.watertight and report.volume_cm3 and report.volume_cm3 > 0


def test_inconsistent_winding_is_fixed():
    s = sphere()
    faces = s.faces.copy()
    flip = np.random.default_rng(2).random(len(faces)) < 0.1
    faces[flip] = faces[flip][:, ::-1]
    _, report = run(trimesh.Trimesh(s.vertices, faces, process=False))
    assert report.watertight
    assert report.volume_cm3 == pytest.approx(run(s)[1].volume_cm3, rel=1e-6)


def test_duplicate_faces_are_removed():
    cube = box(1, 1, 1)
    doubled = trimesh.Trimesh(cube.vertices, np.vstack([cube.faces, cube.faces]), process=False)
    _, report = run(doubled)
    assert report.watertight and report.non_manifold_edges == 0 and report.faces == 12


def test_tiny_floating_specks_are_removed_but_real_parts_stay():
    body = sphere(5)
    speck = sphere(1, 0.01)
    speck.apply_translation([0.9, 0.2, 0])
    _, report = run(trimesh.util.concatenate([body, speck]))
    assert report.fragments_removed == 1 and report.shells == 1

    part = sphere(3, 0.2)
    part.apply_translation([1.0, 0.0, 0])
    _, report = run(trimesh.util.concatenate([body, part]))
    assert report.fragments_removed == 0 and report.shells == 2
    assert any("pièces séparées" in line for line in report.lines())


def test_what_cannot_be_repaired_is_reported_not_hidden():
    """Une arête partagée par trois faces ne se répare pas automatiquement : le rapport doit le dire."""
    cube = box(1, 1, 1)
    vertices = np.vstack([cube.vertices, [[0.5, 0.5, 2.0]]])
    edge = cube.edges_unique[0]
    bad = trimesh.Trimesh(vertices, np.vstack([cube.faces, [[edge[0], edge[1], len(cube.vertices)]]]), process=False)
    _, report = run(bad)
    assert not report.watertight and report.non_manifold_edges >= 1 and report.volume_cm3 is None
    text = " ".join(report.lines())
    assert "NON étanche" in text and "PrusaSlicer" in text


def test_big_meshes_stay_fast():
    import time

    s = sphere(6)  # 81 920 faces, en soupe de triangles : le pire cas pour la soudure
    soup = trimesh.Trimesh(s.vertices[s.faces].reshape(-1, 3), np.arange(len(s.faces) * 3).reshape(-1, 3), process=False)
    started = time.monotonic()
    _, report = run(soup)
    assert report.watertight
    assert time.monotonic() - started < 15


# ---- entrées invalides -----------------------------------------------------------------------------------------------
def test_invalid_inputs_raise_a_clear_error():
    with pytest.raises(ValueError):
        run(trimesh.Trimesh(), 100)
    with pytest.raises(ValueError):
        run(sphere(), 0)
    flat = trimesh.Trimesh([[0, 0, 0], [1, 0, 0], [0, 0, 1]], [[0, 1, 2]], process=False)  # un triangle posé à plat : aucune hauteur
    with pytest.raises(ValueError):
        run(flat, 50)


# ---- fichier STL -----------------------------------------------------------------------------------------------------
def test_export_stl_writes_a_valid_binary_file(tmp_path):
    path = tmp_path / "sous" / "figurine.stl"
    report = printing.export_stl(sphere(), path, height_mm=120)
    data = path.read_bytes()
    assert len(data) == 84 + 50 * report.faces  # STL binaire : 80 octets d'en-tête, 4 de nombre de faces, 50 par face
    loaded = trimesh.load(io.BytesIO(data), file_type="stl")
    assert loaded.is_watertight and loaded.bounds[0][2] == pytest.approx(0.0, abs=1e-4)
    assert loaded.bounds[1][2] == pytest.approx(120.0, abs=1e-3)
    assert loaded.volume > 0


# ---- rapport ---------------------------------------------------------------------------------------------------------
def test_report_texts_are_in_french_and_honest():
    s = sphere(5)
    holey = without(s, np.random.default_rng(3).random(len(s.faces)) < 0.005)
    _, report = run(holey, 150)
    text = "\n".join(report.lines())
    assert "Surface fermée" in text and "150 mm de haut" in text and "cm³" in text
    assert "aplati" in text and "mm pour tenir à plat" in text
    assert report.summary().startswith("surface fermée · ") and "150 mm" in report.summary()
    assert printing._plural(1, "trou fermé", "trous fermés") == "trou fermé"
    assert printing._plural(2, "trou fermé", "trous fermés") == "trous fermés"


# ---- maillage d'un résultat de l'interface ---------------------------------------------------------------------------
def test_source_mesh_uses_the_export_orientation_of_each_engine():
    tall_z = box(1, 1, 3)  # TripoSR brut : l'axe Z est vers le haut
    raw = printing.source_mesh({"engine": "triposr", "mesh": tall_z, "mesh_export": None, "extra": np.eye(3)})
    assert np.ptp(raw.vertices[:, 1]) == pytest.approx(3.0)  # après redressement, c'est Y qui est vers le haut

    tall_y = box(1, 3, 1)  # TripoSG : déjà debout ; « Redresser » est une correction faite à la main
    standing = printing.source_mesh({"engine": "triposg", "mesh": tall_y, "mesh_export": tall_y, "extra": np.eye(3)})
    assert np.ptp(standing.vertices[:, 1]) == pytest.approx(3.0)
    turned = printing.source_mesh({"engine": "triposg", "mesh": tall_y, "mesh_export": tall_y, "extra": rotation("x", -90)})
    assert np.ptp(turned.vertices[:, 1]) == pytest.approx(1.0)  # la correction est prise en compte

    glb = trimesh.Scene(tall_y).export(file_type="glb")
    trellis = printing.source_mesh({"engine": "trellis", "glb": glb, "mesh": tall_y, "mesh_export": tall_y, "extra": np.eye(3)})
    assert np.ptp(trellis.vertices[:, 1]) == pytest.approx(3.0) and len(trellis.faces) == len(tall_y.faces)
    assert ORIENTATION.shape == (3, 3)


def test_size_ratios_announce_the_footprint():
    wide, deep = printing.size_ratios(box(2, 4, 1))  # X = 2, Y (haut) = 4, Z = 1
    assert (wide, deep) == pytest.approx((0.5, 0.25))
    # TripoSR brut : Z vers le haut ; la rotation de l'export amène la hauteur sur Y
    wide, deep = printing.size_ratios(box(2, 1, 4), ORIENTATION)
    assert {round(wide, 6), round(deep, 6)} == {0.5, 0.25}
