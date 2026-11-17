"""Contrôles statiques du paquetage : ce qui est livré, et ce qui ne doit jamais l'être."""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WINDOWS = REPO / "packaging" / "windows"
VERSIONS = json.loads((WINDOWS / "versions.json").read_text(encoding="utf-8"))


def pinned_requirements(lock: Path):
    text = lock.read_text(encoding="utf-8")
    return re.findall(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s\\]+)", text, re.M)


def test_only_triposr_is_vendored():
    # TripoSG : code dérivé de HunyuanDiT, licence qui exclut l'Union européenne (docs/LICENSES.md).
    assert list(VERSIONS["vendor"]) == ["TripoSR"]
    assert re.fullmatch(r"[0-9a-f]{40}", VERSIONS["vendor"]["TripoSR"]["commit"])


@pytest.mark.parametrize("name", ["ThreeRex.iss", "setup_runtime.bat", "versions.json"])
def test_installer_does_not_mention_triposg(name):
    assert "triposg" not in (WINDOWS / name).read_text(encoding="utf-8-sig").lower()


def test_batch_files_are_ascii_with_crlf():
    for bat in WINDOWS.glob("*.bat"):
        raw = bat.read_bytes()
        assert all(b < 128 for b in raw), f"{bat.name} : caractère non ASCII"
        assert raw.count(b"\n") == raw.count(b"\r\n"), f"{bat.name} : fins de ligne non CRLF"


def test_inno_script_basics():
    raw = (WINDOWS / "ThreeRex.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 avec BOM attendu"
    text = raw.decode("utf-8-sig")
    assert "PrivilegesRequired=lowest" in text
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}\r?$", text, re.M)
    assert "setup_runtime.bat" in text and "{param:TORCH|cuda}" in text


def test_lock_file_is_hashed_and_complete():
    lock = REPO / "requirements" / "windows-py311.lock"
    text = lock.read_text(encoding="utf-8")
    pins = pinned_requirements(lock)
    assert len(pins) > 30
    assert text.count("--hash=sha256:") >= len(pins), "chaque paquet doit avoir au moins une somme de contrôle"


def test_lock_file_excludes_torch_and_forbidden_packages():
    names = {name.lower().replace("_", "-") for name, _ in pinned_requirements(REPO / "requirements" / "windows-py311.lock")}
    assert "torch" not in names, "PyTorch s'installe à part, depuis l'index choisi (CUDA ou processeur)"
    for forbidden in ("pymeshlab", "imageio-ffmpeg", "gradio", "diso", "torchmcubes"):
        assert forbidden not in names


def test_lock_matches_declared_direct_dependencies():
    declared = [
        re.split(r"[<>=!\[ ]", line.strip(), maxsplit=1)[0].lower().replace("_", "-")
        for line in (REPO / "requirements" / "main.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    locked = {name.lower().replace("_", "-") for name, _ in pinned_requirements(REPO / "requirements" / "windows-py311.lock")}
    assert [d for d in declared if d not in locked] == []


def test_package_data_is_present():
    assert (REPO / "src" / "threerex" / "assets" / "icon.ico").is_file()
    assert (REPO / "src" / "threerex" / "shims" / "diso" / "__init__.py").is_file()


def test_torch_version_is_pinned():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSIONS["torch"]["version"])
    assert VERSIONS["torch"]["index_cuda"].startswith("https://download.pytorch.org/whl/cu")
    assert VERSIONS["torch"]["index_cpu"].endswith("/cpu")
