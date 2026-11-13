"""Construction de la version commerciale : modules de licence compilés, wheel contrôlée, installateur qui refuse le reste.

Les tests « synthétiques » n'ont besoin de rien. Le test de compilation réelle se saute proprement s'il manque Cython,
`build` ou un compilateur C (sous Windows, c'est MSVC qui est utilisé par le workflow de release, pas par ces tests).
"""

import base64
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packaging"))

import verify_wheel  # noqa: E402

MODULES = verify_wheel.COMPILED_MODULES
PURE_NAME = "imagevers3d-0.1.0-py3-none-any.whl"
COMPILED_NAME = "imagevers3d-0.1.0-cp313-cp313-linux_x86_64.whl"


def make_wheel(folder: Path, name: str, files: list[str]) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        for entry in files:
            archive.writestr(entry, "x")
    return path


def compiled_files(extra: tuple[str, ...] = (), without: tuple[str, ...] = ()) -> list[str]:
    files = ["imagevers3d/__init__.py", "imagevers3d/studio.py"]
    files += [f"imagevers3d/{m}.cpython-313-x86_64-linux-gnu.so" for m in MODULES if m not in without]
    return files + list(extra)


# ---------------------------------------------------------------- contrôle de la wheel (sans compilateur)

def test_pure_python_wheel_is_refused(tmp_path):
    wheel = make_wheel(tmp_path, PURE_NAME, ["imagevers3d/__init__.py"] + [f"imagevers3d/{m}.py" for m in MODULES])
    problems = verify_wheel.check_wheel(wheel)
    assert any("Python pur" in p for p in problems)
    assert any("module compilé absent" in p for p in problems)


def test_complete_compiled_wheel_passes_static_checks(tmp_path):
    wheel = make_wheel(tmp_path, COMPILED_NAME, compiled_files())
    assert verify_wheel.check_wheel(wheel) == []


def test_windows_extension_suffix_is_recognised(tmp_path):
    files = ["imagevers3d/__init__.py"] + [f"imagevers3d/{m}.cp311-win_amd64.pyd" for m in MODULES]
    wheel = make_wheel(tmp_path, "imagevers3d-0.1.0-cp311-cp311-win_amd64.whl", files)
    assert verify_wheel.check_wheel(wheel) == []


@pytest.mark.parametrize("module", MODULES)
def test_missing_binary_is_reported(tmp_path, module):
    wheel = make_wheel(tmp_path, COMPILED_NAME, compiled_files(without=(module,)))
    assert any(module in p and "absent" in p for p in verify_wheel.check_wheel(wheel))


@pytest.mark.parametrize("module", MODULES)
def test_leftover_source_is_reported(tmp_path, module):
    wheel = make_wheel(tmp_path, COMPILED_NAME, compiled_files(extra=(f"imagevers3d/{module}.py",)))
    assert any("source livrée" in p for p in verify_wheel.check_wheel(wheel))


@pytest.mark.parametrize("leftover", ["imagevers3d/license.c", "imagevers3d/license.pyx", "build/license_c/license.py"])
def test_build_leftovers_are_reported(tmp_path, leftover):
    wheel = make_wheel(tmp_path, COMPILED_NAME, compiled_files(extra=(leftover,)))
    assert verify_wheel.check_wheel(wheel)


def test_missing_wheel_is_reported(tmp_path):
    assert verify_wheel.check_wheel(tmp_path / "absente.whl")


def test_dev_wheel_is_accepted_only_when_compilation_is_not_required(tmp_path):
    wheel = make_wheel(tmp_path, PURE_NAME, ["imagevers3d/__init__.py", "imagevers3d/license.py"])
    assert verify_wheel.check_wheel(wheel, require_compiled=False) == []
    assert verify_wheel.check_wheel(wheel, require_compiled=True)


def test_build_stage_refuses_uncompiled_wheel_before_any_download(tmp_path):
    wheel = make_wheel(tmp_path, PURE_NAME, ["imagevers3d/__init__.py", "imagevers3d/license.py"])
    result = subprocess.run(
        [sys.executable, str(REPO / "packaging" / "build_stage.py"), "--wheel", str(wheel),
         "--stage", str(tmp_path / "stage"), "--cache", str(tmp_path / "cache")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Wheel refusée" in result.stderr
    assert not (tmp_path / "cache").exists(), "rien ne doit être téléchargé pour une wheel refusée"
    assert not (tmp_path / "stage").exists()


# ---------------------------------------------------------------- setup.py : valeurs de la version livrée

@pytest.fixture(scope="module")
def setup_module():
    import setuptools

    original = setuptools.setup
    setuptools.setup = lambda *a, **k: None  # setup.py appelle setup() à l'import : on n'en veut que les fonctions
    try:
        spec = importlib.util.spec_from_file_location("i3d_setup", REPO / "setup.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        setuptools.setup = original
    return module


GOOD_KEY = "k1=" + base64.b64encode(bytes(range(32))).decode()


def test_release_values_accepts_valid_input(setup_module, monkeypatch):
    monkeypatch.setenv("I3D_LICENSE_PUBKEYS", GOOD_KEY + ",k2=" + base64.b64encode(bytes(32)).decode())
    monkeypatch.setenv("I3D_LICENSE_URL", "https://licence.exemple.fr/")
    monkeypatch.setenv("I3D_BUY_URL", "https://exemple.fr/acheter")
    keys, url, buy = setup_module.release_values()
    assert set(keys) == {"k1", "k2"}
    assert url == "https://licence.exemple.fr"
    assert buy == "https://exemple.fr/acheter"


@pytest.mark.parametrize(
    "pubkeys, url, buy, expected",
    [
        ("", "https://a.fr", "", "I3D_LICENSE_PUBKEYS est vide"),
        ("k1=pas-du-base64", "https://a.fr", "", "clé publique invalide"),
        ("k1=" + base64.b64encode(b"court").decode(), "https://a.fr", "", "clé publique invalide"),
        ("mauvais id=" + base64.b64encode(bytes(32)).decode(), "https://a.fr", "", "clé publique invalide"),
        (GOOD_KEY, "", "", "https://"),
        (GOOD_KEY, "http://a.fr", "", "https://"),
        (GOOD_KEY, "https://a.fr", "http://achat.fr", "I3D_BUY_URL"),
    ],
)
def test_release_values_rejects_bad_input(setup_module, monkeypatch, pubkeys, url, buy, expected):
    monkeypatch.setenv("I3D_LICENSE_PUBKEYS", pubkeys)
    monkeypatch.setenv("I3D_LICENSE_URL", url)
    monkeypatch.setenv("I3D_BUY_URL", buy)
    with pytest.raises(SystemExit) as error:
        setup_module.release_values()
    assert expected in str(error.value)


def test_compilation_is_opt_in(setup_module, monkeypatch):
    monkeypatch.delenv("I3D_COMPILE_LICENSE", raising=False)
    assert not setup_module.compile_requested()
    assert setup_module.extensions() == []
    monkeypatch.setenv("I3D_COMPILE_LICENSE", "1")
    assert setup_module.compile_requested()


def test_release_workflow_builds_compiled_wheel_and_checks_it():
    text = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'I3D_COMPILE_LICENSE: "1"' in text
    assert "vars.I3D_LICENSE_PUBKEYS" in text and "vars.I3D_LICENSE_URL" in text
    assert "--import-check" in text
    stage_step = text.split("Préparer le dossier de l'installateur")[1].split("Compiler l'installateur")[0]
    assert "py3-none-any" not in stage_step, "l'installateur ne doit recevoir que la wheel compilée"


# ---------------------------------------------------------------- compilation réelle (Cython + compilateur C)

def can_compile() -> bool:
    if importlib.util.find_spec("Cython") is None or importlib.util.find_spec("build") is None:
        return False
    if importlib.util.find_spec("cryptography") is None:
        return False
    return any(shutil.which(c) for c in ("cc", "gcc", "clang", "cl"))


ROUND_TRIP = r"""
import base64, json, os, sys, time
sys.path.insert(0, sys.argv[1])
from imagevers3d import license as lic, _licproto as proto, _license_keys as keys

# Réglages de développement : sans effet dans la version compilée.
assert lic.is_compiled()
assert "dev" not in lic.public_keys()
assert lic.server_url() == "https://licence.exemple.fr"

# Un vrai jeton, signé hors de la version compilée, est accepté par la version compilée ; une altération est refusée.
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(sys.argv[2]))
payload = {"v": 1, "kid": "k1", "typ": "license", "lid": "L1", "did": "a" * 32, "iat": int(time.time()), "exp": None,
           "plan": "personal", "dev": 2}
raw = proto.canonical_json(payload)
token = proto.encode_token(raw, private.sign(proto.signing_message(raw)))
assert proto.verify_token(token, lic.public_keys())["lid"] == "L1"
tampered = proto.encode_token(proto.canonical_json({**payload, "lid": "L2"}), proto.split_token(token)[1])
try:
    proto.verify_token(tampered, lic.public_keys())
except proto.LicenseError as error:
    assert error.code == "bad_signature", error.code
else:
    raise SystemExit("jeton altéré accepté")

# Une licence de développement signée avec une AUTRE clé, même déclarée par l'environnement, ne débloque rien.
other = Ed25519PrivateKey.generate()
raw = proto.canonical_json({**payload, "kid": "dev"})
forged = proto.encode_token(raw, other.sign(proto.signing_message(raw)))
try:
    proto.verify_token(forged, lic.public_keys())
except proto.LicenseError as error:
    assert error.code == "unknown_key", error.code
else:
    raise SystemExit("jeton de développement accepté par la version compilée")
print("ok")
"""


@pytest.fixture(scope="module")
def compiled_wheel(tmp_path_factory):
    if not can_compile():
        pytest.skip("Cython, build, cryptography ou un compilateur C manque : compilation réelle non testée ici")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    work = tmp_path_factory.mktemp("build_commercial")
    for item in ("src", "requirements"):
        shutil.copytree(REPO / item, work / item, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    for item in ("setup.py", "pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO / item, work / item)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    secret = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    env = dict(
        os.environ,
        I3D_COMPILE_LICENSE="1",
        I3D_LICENSE_PUBKEYS="k1=" + base64.b64encode(public).decode(),
        I3D_LICENSE_URL="https://licence.exemple.fr",
        I3D_BUY_URL="https://exemple.fr/acheter",
    )
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(work / "dist")],
        cwd=work, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip("la compilation n'a pas abouti sur cette machine :\n" + (result.stdout + result.stderr)[-1500:])
    wheels = list((work / "dist").glob("imagevers3d-*.whl"))
    assert len(wheels) == 1
    return wheels[0], base64.b64encode(secret).decode()


def test_compiled_wheel_contains_binaries_and_no_sources(compiled_wheel):
    wheel, _ = compiled_wheel
    assert verify_wheel.check_wheel(wheel, require_compiled=True, import_check=True) == []
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    for module in MODULES:
        assert f"imagevers3d/{module}.py" not in names
    assert "imagevers3d/studio.py" in names, "le reste du logiciel reste en Python lisible (seule la licence est compilée)"


def test_compiled_wheel_embeds_values_but_not_private_material(compiled_wheel):
    wheel, secret = compiled_wheel
    with zipfile.ZipFile(wheel) as archive:
        blobs = [archive.read(n) for n in archive.namelist() if n.endswith((".so", ".pyd"))]
    assert blobs
    joined = b"".join(blobs)
    assert b"licence.exemple.fr" in joined, "l'adresse du serveur est écrite dans le binaire"
    assert base64.b64decode(secret) not in joined and secret.encode() not in joined


def test_compiled_modules_verify_real_signatures_and_ignore_dev_settings(compiled_wheel, tmp_path):
    wheel, secret = compiled_wheel
    folder = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(folder)
    env = dict(
        os.environ,
        IMAGEVERS3D_DEV_LICENSE_PUBKEY=base64.b64encode(bytes(range(32))).decode(),
        IMAGEVERS3D_LICENSE_URL="http://127.0.0.1:9",
        IMAGEVERS3D_DATA=str(tmp_path / "data"),
    )
    result = subprocess.run([sys.executable, "-I", "-c", ROUND_TRIP, str(folder), secret], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_repository_is_left_untouched_by_the_build(compiled_wheel):
    # La compilation travaille sur une copie (build/license_c) : jamais sur les sources suivies par git.
    for module in MODULES:
        assert (REPO / "src" / "imagevers3d" / f"{module}.py").is_file()
    keys = (REPO / "src" / "imagevers3d" / "_license_keys.py").read_text(encoding="utf-8")
    assert "KEYS: dict[str, str] = {}" in keys and 'SERVER_URL: str = ""' in keys
