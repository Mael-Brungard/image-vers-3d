"""Moteur « Qualité maximale » (trellis_runner) : lancement, avancement, repli mémoire, erreurs, export, installation.

Le vrai programme (trellis-cli.exe) a besoin d'une carte NVIDIA et de plusieurs Go de poids : ici, un faux programme
en Python reprend ses options et ses sorties, et un petit serveur HTTP local joue GitHub et Hugging Face."""

import hashlib
import io
import json
import os
import sys
import textwrap
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from threerex import trellis_runner as tr

FAKE = '''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
src, out = args[0], Path(args[1])
opts, flags, i = {}, [], 2
while i < len(args):
    if args[i] in ("--models", "--res", "--steps", "--seed", "--bg-removal", "--webp", "--atlas", "--tex-res"):
        opts[args[i]] = args[i + 1]; i += 2
    else:
        flags.append(args[i]); i += 1
models = Path(opts["--models"])
behavior = (models / "behavior.txt").read_text().strip() if (models / "behavior.txt").exists() else "ok"
(models / "last_args.json").write_text(json.dumps({"opts": opts, "flags": flags, "src": src, "out": str(out), "cwd": os.getcwd(), "argv": args}))
print("[trellis] using CUDA0 -- fake (12000 MB)", flush=True)
if behavior == "hang":
    time.sleep(30)
if behavior == "gpu":
    print("[trellis] no usable GPU backend found and --require-gpu is set; refusing CPU fallback.", flush=True); sys.exit(1)
if behavior == "crash":
    print("boum", flush=True); sys.exit(3)
if behavior == "retry-crash":
    print("ggml_cuda: alloc failed, retrying with smaller chunk", flush=True); print("boum", flush=True); sys.exit(3)
if behavior == "oom-early":
    print("cudaMalloc failed: out of memory", flush=True)
    for n in range(300):
        print("  step %d" % n, flush=True)
    sys.exit(1)
if behavior == "oom-recovered":
    print("cudaMalloc failed: out of memory -- retrying with smaller tiles", flush=True)
if (behavior == "oom" or (behavior == "oom1024" and opts["--res"] == "1024") or (behavior == "oom1536" and opts["--res"] == "1536")
        or (behavior == "oom-big" and int(opts["--res"]) >= 1024) or (behavior == "oom-fine" and "--atlas" in opts)):
    print("ggml_backend_cuda_buffer_type_alloc_buffer: allocating 18000 MiB on device 0: cudaMalloc failed: out of memory", flush=True)
    sys.exit(1)
if "--bg-only" in flags:
    if behavior != "nocutout":
        from PIL import Image
        Image.new("RGBA", (48, 48), (10, 200, 30, 255)).save(out.with_name(out.stem + "_cutout.png"))
    sys.exit(0)
print("      bg-removal cutout -> x", flush=True)
time.sleep(0.4)
print("  remesh postproc: dropped 2 floater comps -> V=8 F=12", flush=True)
time.sleep(0.2)
import trimesh
from PIL import Image
box = trimesh.creation.box(extents=(1.0, 2.0, 3.0))
uv = box.vertices[:, :2] * 0.0 + 0.5
material = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new("RGB", (8, 8), (220, 30, 20)))
box.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
box.export(str(out))
print("done in 0.6s -> " + str(out), flush=True)
'''


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(tr, "HEARTBEAT_SECONDS", 0.05)


@pytest.fixture(autouse=True)
def _rearm():
    tr.reset_cancel()
    yield
    tr.reset_cancel()


def make_runner(tmp_path, behavior="ok", files=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_trellis.py"
    script.write_text(textwrap.dedent(FAKE), encoding="utf-8")
    runner = tr.TrellisRunner(base=tmp_path / "trellis", launcher=[sys.executable, str(script)], quant="q4")
    if files:
        runner.models_dir.mkdir(parents=True)
        for name in tr.MODEL_FILES:
            (runner.models_dir / name).write_bytes(b"gguf")
        (runner.models_dir / "behavior.txt").write_text(behavior)
    return runner


def image(mode="RGB"):
    return Image.new(mode, (64, 48), (120, 120, 120) if mode == "RGB" else (120, 120, 120, 255))


def last_args(runner):
    return json.loads((runner.models_dir / "last_args.json").read_text())


# ---- calcul ------------------------------------------------------------------------------------------------------------
def test_not_ready_without_models(tmp_path):
    runner = make_runner(tmp_path, files=False)
    assert not runner.ready() and runner.missing_models() == list(tr.MODEL_FILES)
    with pytest.raises(RuntimeError, match="pas encore installé"):
        runner.generate(image(), "detaille", True, 42, lambda m: None)


def test_generate_builds_the_command_and_returns_a_coloured_preview(tmp_path, fast):
    runner = make_runner(tmp_path)
    messages = []
    result = runner.generate(image(), "detaille", True, 7, messages.append)
    args = last_args(runner)
    assert args["opts"] == {"--models": os.path.join("models", "q4"), "--res": "1024", "--steps": "12", "--seed": "7",
                            "--bg-removal": "birefnet", "--webp": "off"}
    assert "--require-gpu" in args["flags"]  # jamais de repli silencieux sur le processeur (très lent, énorme en RAM)
    assert result["glb"].startswith(b"glTF") and result["res"] == 1024 and result["notes"] == []
    colours = np.asarray(result["mesh"].visual.vertex_colors)
    assert result["mesh"].visual.kind == "vertex" and colours[:, 0].min() > 200 and colours[:, 1].max() < 60
    assert any("Nettoyage du maillage" in m for m in messages)  # étape reconnue dans la sortie du programme
    assert any(" min " in m and " s" in m for m in messages)  # sans nouvelle ligne, le temps écoulé s'affiche quand même
    assert list((runner.base / "work").iterdir()) == []  # dossier de travail supprimé


@pytest.mark.parametrize(
    "quality, res, steps",
    [("rapide", "512", "12"), ("detaille", "1024", "12"), ("maximum", "1024", "24"), ("ultra", "1536", "12")],
)
def test_quality_presets(tmp_path, fast, quality, res, steps):
    runner = make_runner(tmp_path)
    runner.generate(image(), quality, True, 42, lambda m: None)
    opts = last_args(runner)["opts"]
    assert (opts["--res"], opts["--steps"]) == (res, steps)


@pytest.mark.parametrize(
    "picture, remove_bg, expected",
    [("rgb", True, "birefnet"), ("rgb", False, "threshold"), ("alpha", True, "auto"), ("alpha", False, "auto"),
     ("opaque-rgba", True, "birefnet")],
)
def test_background_modes(tmp_path, fast, picture, remove_bg, expected):
    runner = make_runner(tmp_path)
    if picture == "alpha":
        img = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    else:
        img = image("RGBA" if picture == "opaque-rgba" else "RGB")
    runner.generate(img, "rapide", remove_bg, 1, lambda m: None)
    assert last_args(runner)["opts"]["--bg-removal"] == expected


def test_out_of_memory_in_1024_falls_back_to_512(tmp_path, fast):
    runner = make_runner(tmp_path, "oom1024")
    messages = []
    result = runner.generate(image(), "maximum", True, 42, messages.append)
    note = tr.FALLBACK_NOTE.format(old=1024, new=512)
    assert result["res"] == 512 and result["notes"] == [note]
    assert note in messages and last_args(runner)["opts"]["--res"] == "512"


def test_out_of_memory_everywhere_gives_actionable_message(tmp_path, fast):
    runner = make_runner(tmp_path, "oom")
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "detaille", True, 42, lambda m: None)
    assert str(info.value) == tr.MEMORY_HINT
    assert isinstance(info.value.__cause__, tr.MemoryFailure)
    runner_512 = make_runner(tmp_path / "b", "oom")
    with pytest.raises(RuntimeError) as info:
        runner_512.generate(image(), "rapide", True, 42, lambda m: None)  # déjà en 512 : pas de repli possible
    assert str(info.value) == tr.MEMORY_HINT


def test_gpu_unavailable_points_to_the_driver(tmp_path, fast):
    runner = make_runner(tmp_path, "gpu")
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert str(info.value) == tr.DRIVER_HINT and "580" in tr.DRIVER_HINT


def test_unknown_failure_keeps_code_and_last_line(tmp_path, fast):
    runner = make_runner(tmp_path, "crash")
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert "code 3" in str(info.value) and "boum" in str(info.value)
    assert isinstance(info.value.__cause__, tr.WorkerOutput) and "boum" in str(info.value.__cause__)


def test_timeout_kills_the_program(tmp_path, fast, monkeypatch):
    monkeypatch.setattr(tr, "TIMEOUT_SECONDS", 0.5)
    runner = make_runner(tmp_path, "hang")
    with pytest.raises(RuntimeError, match="dépassé"):
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert not tr._LIVE


def test_cutout_preview(tmp_path, fast):
    runner = make_runner(tmp_path)
    cut = runner.cutout(image(), True, lambda m: None)
    assert cut is not None and cut.mode == "RGBA" and cut.size == (48, 48)
    flags = last_args(runner)["flags"]
    assert "--bg-only" in flags and "--dump-bg" in flags
    (runner.models_dir / "behavior.txt").write_text("nocutout")
    assert runner.cutout(image(), True, lambda m: None) is None  # rien écrit : l'appelant se rabat sur un autre détourage
    (runner.models_dir / "behavior.txt").write_text("crash")
    assert runner.cutout(image(), True, lambda m: None) is None


# ---- aperçu et export ------------------------------------------------------------------------------------------------
@pytest.fixture
def glb(tmp_path, fast):
    return make_runner(tmp_path).generate(image(), "rapide", True, 42, lambda m: None)["glb"]


def test_export_glb_is_identical_without_rotation(glb, tmp_path):
    for rotation in (None, np.eye(3)):
        path = tr.export_glb(glb, tmp_path / "sortie" / "a.glb", rotation)
        assert path.read_bytes() == glb


def test_export_glb_with_rotation_turns_the_model_and_keeps_the_texture(glb, tmp_path):
    turn = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1])[:3, :3]
    path = tr.export_glb(glb, tmp_path / "b.glb", turn)
    mesh = trimesh.load(str(path), force="mesh")
    assert np.allclose(sorted(mesh.extents), [1, 2, 3], atol=1e-4)
    assert np.allclose(mesh.extents, [2, 1, 3], atol=1e-4)  # X et Y échangés par le quart de tour autour de Z
    assert mesh.visual.kind == "texture" and mesh.visual.material.baseColorTexture is not None


def test_export_obj_has_material_and_texture(glb, tmp_path):
    path = tr.export_glb(glb, tmp_path / "c.obj")
    assert path.exists() and "mtllib" in path.read_text()
    assert list(tmp_path.glob("*.mtl")) and list(tmp_path.glob("*.png"))


# ---- installation --------------------------------------------------------------------------------------------------
def sha(data):
    return hashlib.sha256(data).hexdigest()


def program_zip(extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(tr.EXE_NAME, b"MZ fake exe")
        archive.writestr("ggml.dll", b"dll")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


class Site:
    """Joue GitHub (/program.zip) et Hugging Face (/hf/.../<nom> -> redirection vers /cdn/<nom>, avec X-Linked-ETag)."""

    def __init__(self):
        self.files = {"/program.zip": program_zip()}
        for name in tr.MODEL_FILES:
            self.files[f"/cdn/{name}"] = (name * 50).encode()
        self.etag_override = None
        self.cut_after = None  # coupe la connexion après N octets (une seule fois)
        self.hits = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                site.hits.append((self.path, self.headers.get("Range")))
                if "/resolve/" in self.path:
                    name = self.path.rsplit("/", 1)[1]
                    data = site.files[f"/cdn/{name}"]
                    self.send_response(302)
                    self.send_header("Location", f"/cdn/{name}")
                    self.send_header("X-Linked-ETag", f'"{site.etag_override or sha(data)}"')
                    self.end_headers()
                    return
                data = site.files.get(self.path)
                if data is None:
                    self.send_error(404)
                    return
                start = 0
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng.split("=")[1].split("-")[0])
                    if start >= len(data):
                        self.send_response(416)
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(data) - start))
                self.end_headers()
                body = data[start:]
                if site.cut_after is not None:
                    body, site.cut_after = body[: site.cut_after], None
                self.wfile.write(body)
                self.wfile.flush()
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    s = Site()
    monkeypatch.setattr(tr, "PROGRAM_URL", s.url + "/program.zip")
    monkeypatch.setattr(tr, "PROGRAM_SHA256", sha(s.files["/program.zip"]))
    monkeypatch.setattr(tr, "WEIGHTS_BASE", s.url + "/hf")
    monkeypatch.setattr(tr, "PROGRAM_BYTES", 10_000)
    monkeypatch.setattr(tr, "WEIGHTS_BYTES", {"q4": 10_000, "q8": 20_000})
    yield s
    s.close()


def fresh(tmp_path, windows=True, smoke=False):
    runner = tr.TrellisRunner(base=tmp_path / "trellis", launcher=None, quant="q4", windows=windows, nvidia=True)
    if not smoke:  # le faux « .exe » n'est pas exécutable sous Linux
        runner._smoke_test = lambda command: None
    return runner


def test_install_downloads_program_and_weights(site, tmp_path, monkeypatch):
    runner = fresh(tmp_path)
    assert runner.supported() and not runner.ready() and runner.download_size() > 0
    messages = []
    runner.install(messages.append)
    assert runner.ready() and runner.download_size() == 0
    assert (runner.program_dir / tr.EXE_NAME).exists() and (runner.program_dir / "VERSION.txt").read_text() == tr.RELEASE_TAG
    assert not (tmp_path / "trellis" / "downloads" / tr.PROGRAM_ASSET).exists()  # l'archive est supprimée après usage
    assert not list((tmp_path / "trellis").rglob("*.part"))
    assert messages[-1] == "Moteur Qualité maximale installé."
    hits = len(site.hits)
    runner.install(messages.append)  # déjà installé : rien à retélécharger
    assert len(site.hits) == hits


def test_install_only_fetches_what_is_missing(site, tmp_path, monkeypatch):
    runner = fresh(tmp_path)
    runner.install(lambda m: None)
    (runner.models_dir / "tex_dec.gguf").unlink()
    site.hits.clear()
    runner.install(lambda m: None)
    assert [h[0] for h in site.hits if "/resolve/" in h[0]] == [f"/hf/{tr.WEIGHTS_REPO}/resolve/{tr.WEIGHTS_REVISION}/q4/tex_dec.gguf"]
    assert runner.ready()


def test_download_resumes_a_partial_file(site, tmp_path):
    data = site.files["/cdn/ss_flow.gguf"]
    dest = tmp_path / "ss_flow.gguf"
    dest.with_name(dest.name + ".part").write_bytes(data[:100])
    tr.download(site.url + "/cdn/ss_flow.gguf", dest, sha256=sha(data))
    assert dest.read_bytes() == data
    assert site.hits[-1] == ("/cdn/ss_flow.gguf", "bytes=100-")


def test_download_of_an_already_complete_part_is_verified(site, tmp_path):
    data = site.files["/cdn/ss_flow.gguf"]
    dest = tmp_path / "x.gguf"
    dest.with_name("x.gguf.part").write_bytes(data)  # le serveur répond 416 : tout est déjà là
    tr.download(site.url + "/cdn/ss_flow.gguf", dest, sha256=sha(data))
    assert dest.read_bytes() == data


def test_interrupted_download_can_be_resumed(site, tmp_path):
    data = site.files["/cdn/ss_flow.gguf"]
    dest = tmp_path / "ss_flow.gguf"
    site.cut_after = 120
    with pytest.raises(tr.DownloadError, match="incomplet|interrompu"):
        tr.download(site.url + "/cdn/ss_flow.gguf", dest, sha256=sha(data))
    assert not dest.exists() and dest.with_name(dest.name + ".part").stat().st_size == 120
    tr.download(site.url + "/cdn/ss_flow.gguf", dest, sha256=sha(data))
    assert dest.read_bytes() == data


def test_corrupted_weights_are_rejected(site, tmp_path, monkeypatch):
    site.etag_override = "0" * 64  # la somme annoncée ne correspond pas au contenu
    runner = fresh(tmp_path)
    with pytest.raises(tr.DownloadError, match="corrompu"):
        runner.install(lambda m: None)
    assert runner.program_ready() and not runner.ready()  # le programme est bon, les poids refusés
    assert not list(runner.models_dir.glob("*"))  # ni fichier final ni reste partiel


def test_program_with_wrong_checksum_is_rejected(site, tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "PROGRAM_SHA256", "f" * 64)
    runner = fresh(tmp_path)
    with pytest.raises(tr.DownloadError, match="corrompu"):
        runner.install(lambda m: None)
    assert not runner.program_ready()


def test_archive_with_path_traversal_is_refused(tmp_path):
    archive = tmp_path / "a.zip"
    archive.write_bytes(program_zip({"../evil.txt": b"x"}))
    with pytest.raises(tr.DownloadError, match="suspect"):
        tr.extract_program(archive, tmp_path / "program")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "program").exists()


def test_archive_without_the_program_is_refused(tmp_path):
    archive = tmp_path / "a.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("autre.txt", b"x")
    archive.write_bytes(buffer.getvalue())
    with pytest.raises(tr.DownloadError, match="absent"):
        tr.extract_program(archive, tmp_path / "program")


def test_install_refuses_when_the_disk_is_too_small(site, tmp_path, monkeypatch):
    monkeypatch.setattr(tr.shutil, "disk_usage", lambda p: type("U", (), {"free": 1000})())
    with pytest.raises(tr.DownloadError, match="Pas assez de place"):
        fresh(tmp_path).install(lambda m: None)


def test_network_failure_message_mentions_resuming(tmp_path):
    with pytest.raises(tr.DownloadError, match="reprendra"):
        tr.download("http://127.0.0.1:9/inexistant", tmp_path / "x", sha256=None)


def test_new_program_version_reinstalls_only_the_program(site, tmp_path, monkeypatch):
    runner = fresh(tmp_path)
    runner.install(lambda m: None)
    (runner.program_dir / "VERSION.txt").write_text("v0.0.1")
    assert not runner.program_ready() and runner.missing_models() == []
    site.hits.clear()
    runner.install(lambda m: None)
    assert runner.ready() and [h[0] for h in site.hits] == ["/program.zip"]


def test_not_supported_outside_windows_without_override(tmp_path, monkeypatch):
    monkeypatch.delenv("THREEREX_TRELLIS_EXE", raising=False)
    runner = fresh(tmp_path, windows=False)
    assert not runner.supported() and not runner.ready()
    with pytest.raises(RuntimeError, match="Windows"):
        runner.install(lambda m: None)


# ---- robustesse (relecture critique) --------------------------------------------------------------------------------------
def test_program_receives_only_ascii_relative_paths_even_with_an_accented_home(tmp_path, fast):
    runner = make_runner(tmp_path / "Maël Brüngard" / "données")
    runner.generate(image(), "rapide", True, 42, lambda m: None)
    args = last_args(runner)
    assert Path(args["cwd"]).resolve() == runner.base.resolve()  # lancé depuis le dossier du moteur
    for value in (args["src"], args["out"], args["opts"]["--models"]):
        assert value.isascii() and not os.path.isabs(value), value
    assert all(a.isascii() for a in args["argv"])
    assert (runner.base / "work").is_dir() and list((runner.base / "work").iterdir()) == []


def test_old_work_folders_are_cleaned_up(tmp_path, fast):
    runner = make_runner(tmp_path)
    old, recent = runner.base / "work" / "told", runner.base / "work" / "tnew"
    for folder in (old, recent):
        folder.mkdir(parents=True)
    long_ago = time.time() - 24 * 3600
    os.utime(old, (long_ago, long_ago))
    runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert not old.exists() and recent.exists()


def test_old_out_of_memory_message_is_not_lost_in_a_long_log(tmp_path, fast):
    runner = make_runner(tmp_path, "oom-early")  # le message sort des 120 dernières lignes conservées
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert str(info.value) == tr.MEMORY_HINT


def test_recovered_allocation_failure_is_not_an_error(tmp_path, fast):
    runner = make_runner(tmp_path, "oom-recovered")  # « alloc failed, retrying » puis succès
    result = runner.generate(image(), "detaille", True, 42, lambda m: None)
    assert result["res"] == 1024 and result["notes"] == []


def test_retry_message_does_not_turn_a_crash_into_a_memory_error(tmp_path, fast):
    runner = make_runner(tmp_path, "retry-crash")
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "detaille", True, 42, lambda m: None)
    assert "code 3" in str(info.value) and not isinstance(info.value.__cause__, tr.MemoryFailure)


@pytest.mark.parametrize("code", [0xC0000135, 3221225781, -1073741515, 0xC000007B])
def test_windows_loader_failures_give_the_start_hint(code):
    with pytest.raises(RuntimeError) as info:
        tr.TrellisRunner._fail(code, ["rien"])
    assert str(info.value) == tr.START_HINT


def test_program_that_cannot_start_gives_the_start_hint(tmp_path, fast):
    runner = make_runner(tmp_path)
    runner.launcher = [str(tmp_path / "absent" / "trellis-cli.exe")]
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert str(info.value) == tr.START_HINT and isinstance(info.value.__cause__, OSError)


def test_cancel_all_stops_the_program_and_frees_the_gpu(tmp_path, fast):
    runner = make_runner(tmp_path, "hang")
    errors = []

    def work():
        try:
            runner.generate(image(), "rapide", True, 42, lambda m: None)
        except RuntimeError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=work)
    started = time.monotonic()
    thread.start()
    for _ in range(100):
        if tr._LIVE:
            break
        time.sleep(0.05)
    assert tr._LIVE
    tr.cancel_all()
    thread.join(10)
    assert not thread.is_alive() and time.monotonic() - started < 15  # sans l'annulation : 30 s de « hang »
    assert errors == [tr.CANCELLED] and not tr._LIVE


def test_nothing_starts_after_cancel_all(tmp_path, fast, site):
    tr.cancel_all()
    runner = make_runner(tmp_path)
    with pytest.raises(RuntimeError, match="annulée"):
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    with pytest.raises(tr.DownloadError, match="annulée"):
        tr.download(site.url + "/cdn/ss_flow.gguf", tmp_path / "x.gguf", sha256=None)
    assert not (tmp_path / "x.gguf").exists()


def test_transparency_needs_a_real_cutout():
    corners = Image.new("RGBA", (100, 100), (10, 10, 10, 255))
    corners.putpixel((0, 0), (0, 0, 0, 0))  # un pixel transparent dans une photo : ce n'est pas une image détourée
    assert not tr.has_real_alpha(corners)
    cutout = Image.new("RGBA", (100, 100), (10, 10, 10, 255))
    cutout.paste((0, 0, 0, 0), (0, 0, 100, 20))
    assert tr.has_real_alpha(cutout) and not tr.has_real_alpha(Image.new("RGB", (8, 8)))


def test_obj_export_names_its_files_after_the_model(glb, tmp_path):
    for name in ("figurine_a", "figurine_b"):
        tr.export_glb(glb, tmp_path / f"{name}.obj")
    for name in ("figurine_a", "figurine_b"):
        text = (tmp_path / f"{name}.obj").read_text()
        assert f"mtllib {name}.mtl" in text
        assert f"{name}_texture" in (tmp_path / f"{name}.mtl").read_text()
    assert len(list(tmp_path.glob("*.png"))) == 2  # deux textures distinctes : le second export n'écrase pas le premier


def test_http_error_names_the_status(site, tmp_path):
    with pytest.raises(tr.DownloadError, match="404"):
        tr.download(site.url + "/nexiste-pas", tmp_path / "x.gguf", sha256=None)


def test_weights_revision_is_pinned_and_the_program_dir_is_versioned(tmp_path):
    assert len(tr.WEIGHTS_REVISION) == 40 and tr.WEIGHTS_REVISION != "main"
    assert fresh(tmp_path).program_dir.name == f"program-{tr.RELEASE_TAG}"


def test_install_removes_old_program_versions(site, tmp_path):
    runner = fresh(tmp_path)
    for name in ("program", "program-v0.0.1"):
        (runner.base / name).mkdir(parents=True)
        (runner.base / name / "vieux.dll").write_bytes(b"x")
    runner.install(lambda m: None)
    assert runner.ready() and not (runner.base / "program").exists() and not (runner.base / "program-v0.0.1").exists()


def test_failed_start_check_keeps_the_archive_and_reinstalls_without_downloading_again(site, tmp_path):
    runner = fresh(tmp_path, smoke=True)
    checks = []

    def smoke(command):
        checks.append(command)
        if len(checks) == 1:
            raise RuntimeError(tr.START_HINT)

    runner._smoke_test = smoke
    with pytest.raises(RuntimeError) as info:
        runner.install(lambda m: None)
    assert str(info.value) == tr.START_HINT
    assert not runner.program_dir.exists() and (runner.base / "downloads" / tr.PROGRAM_ASSET).is_file()
    site.hits.clear()
    runner.install(lambda m: None)  # l'archive vérifiée est réutilisée
    assert runner.ready() and "/program.zip" not in [h[0] for h in site.hits]
    assert not (runner.base / "downloads" / tr.PROGRAM_ASSET).exists()
    assert len(checks) == 2


def test_start_check_accepts_a_program_that_starts_and_rejects_one_that_does_not(tmp_path):
    runner = fresh(tmp_path, smoke=True)
    runner.base.mkdir(parents=True)
    runner._smoke_test = tr.TrellisRunner._smoke_test.__get__(runner)
    runner._smoke_test([sys.executable, "-c", "import sys; print('usage'); sys.exit(1)"])  # erreur d'usage = il démarre
    with pytest.raises(RuntimeError) as info:
        runner._smoke_test([str(tmp_path / "absent.exe")])
    assert str(info.value) == tr.START_HINT


def test_start_check_tolerates_a_program_that_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "SMOKE_TIMEOUT", 0.3)
    runner = fresh(tmp_path, smoke=True)
    runner.base.mkdir(parents=True)
    runner._smoke_test = tr.TrellisRunner._smoke_test.__get__(runner)
    runner._smoke_test([sys.executable, "-c", "import time; time.sleep(5)"])


def test_engine_is_only_offered_with_an_nvidia_driver(tmp_path):
    runner = tr.TrellisRunner(base=tmp_path / "t", launcher=None, quant="q4", windows=True, nvidia=False)
    assert not runner.supported() and not runner.ready()
    with pytest.raises(RuntimeError, match="NVIDIA"):
        runner.install(lambda m: None)
    assert tr.TrellisRunner(base=tmp_path / "t", launcher=None, quant="q4", windows=True, nvidia=True).supported()


def test_nvidia_driver_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(tr.shutil, "which", lambda name: None)
    (tmp_path / "System32").mkdir()
    assert not tr.has_nvidia_driver(True, str(tmp_path))
    (tmp_path / "System32" / "nvcuda.dll").write_bytes(b"x")
    assert tr.has_nvidia_driver(True, str(tmp_path)) and not tr.has_nvidia_driver(False, str(tmp_path))
    monkeypatch.setattr(tr.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    assert tr.has_nvidia_driver(False, str(tmp_path))


# ---- qualité maximale : 1536, texture très fine, précision des poids -----------------------------------------------------
def test_ultra_preset_is_1536_and_standard_texture_sends_no_atlas_option(tmp_path, fast):
    runner = make_runner(tmp_path)
    result = runner.generate(image(), "ultra", True, 42, lambda m: None)
    opts = last_args(runner)["opts"]
    assert opts["--res"] == "1536" and "--atlas" not in opts and "--tex-res" not in opts
    assert result["res"] == 1536 and result["fine"] is False and result["notes"] == []


def test_fine_texture_asks_for_a_4k_atlas_and_a_1024_pbr_decode(tmp_path, fast):
    runner = make_runner(tmp_path)
    result = runner.generate(image(), "detaille", True, 42, lambda m: None, texture="fine")
    opts = last_args(runner)["opts"]
    assert (opts["--atlas"], opts["--tex-res"]) == ("4096", "1024") and result["fine"] is True and result["notes"] == []


def test_fine_texture_is_pointless_in_512(tmp_path, fast):
    runner = make_runner(tmp_path)
    result = runner.generate(image(), "rapide", True, 42, lambda m: None, texture="fine")
    assert "--atlas" not in last_args(runner)["opts"] and result["fine"] is False


def test_fine_texture_falls_back_to_standard_texture_before_lowering_the_resolution(tmp_path, fast):
    runner = make_runner(tmp_path, "oom-fine")
    messages = []
    result = runner.generate(image(), "detaille", True, 42, messages.append, texture="fine")
    assert result["res"] == 1024 and result["fine"] is False and result["notes"] == [tr.FALLBACK_TEXTURE_NOTE]
    assert tr.FALLBACK_TEXTURE_NOTE in messages and "--atlas" not in last_args(runner)["opts"]


def test_ultra_falls_back_to_1024(tmp_path, fast):
    runner = make_runner(tmp_path, "oom1536")
    result = runner.generate(image(), "ultra", True, 42, lambda m: None)
    assert result["res"] == 1024 and result["notes"] == [tr.FALLBACK_NOTE.format(old=1536, new=1024)]


def test_ultra_can_fall_all_the_way_to_512_and_says_so(tmp_path, fast):
    runner = make_runner(tmp_path, "oom-big")
    result = runner.generate(image(), "ultra", True, 42, lambda m: None, texture="fine")
    assert result["res"] == 512 and result["fine"] is False
    assert result["notes"] == [tr.FALLBACK_TEXTURE_NOTE, tr.FALLBACK_NOTE.format(old=1536, new=1024),
                               tr.FALLBACK_NOTE.format(old=1024, new=512)]


def test_ladder_order():
    ladder = tr.TrellisRunner._ladder
    assert [(p.res, f) for p, f in ladder(tr.PRESETS["ultra"], True)] == [(1536, True), (1536, False), (1024, False), (512, False)]
    assert [(p.res, f) for p, f in ladder(tr.PRESETS["maximum"], False)] == [(1024, False), (512, False)]
    assert [(p.res, f) for p, f in ladder(tr.PRESETS["rapide"], True)] == [(512, False)]


def test_precision_switch_changes_the_model_folder_and_what_is_missing(tmp_path):
    runner = make_runner(tmp_path)
    assert runner.quant == "q4" and runner.ready()
    runner.set_quant("q8")
    assert runner.models_dir == runner.base / "models" / "q8" and not runner.ready()
    assert runner.missing_models() == list(tr.MODEL_FILES) and runner.download_size() == tr.WEIGHTS_BYTES["q8"]
    runner.set_quant("q4")
    assert runner.ready()
    with pytest.raises(ValueError):
        runner.set_quant("q2")


def test_q8_memory_failure_suggests_going_back_to_standard(tmp_path, fast):
    runner = make_runner(tmp_path, "oom", files=False)
    runner.set_quant("q8")
    runner.models_dir.mkdir(parents=True)
    for name in tr.MODEL_FILES:
        (runner.models_dir / name).write_bytes(b"gguf")
    (runner.models_dir / "behavior.txt").write_text("oom")
    with pytest.raises(RuntimeError) as info:
        runner.generate(image(), "rapide", True, 42, lambda m: None)
    assert "précision Haute" in str(info.value) and str(info.value).startswith(tr.MEMORY_HINT)


def test_q8_weights_are_downloaded_into_their_own_folder(site, tmp_path):
    runner = fresh(tmp_path)
    runner.install(lambda m: None)
    runner.set_quant("q8")
    assert not runner.ready() and runner.program_ready()
    site.hits.clear()
    runner.install(lambda m: None)
    assert runner.ready() and (runner.base / "models" / "q8" / "ss_flow.gguf").is_file() and (runner.base / "models" / "q4").is_dir()
    assert "/program.zip" not in [h[0] for h in site.hits] and all("/q8/" in h[0] for h in site.hits if "/resolve/" in h[0])
