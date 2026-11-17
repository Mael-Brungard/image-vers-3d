"""Teste threerex.triposg_worker de bout en bout avec de faux torch / huggingface_hub / triposg (pas de GPU requis)."""
import os, subprocess, sys, tempfile, textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
failed = 0
def check(label, ok):
    global failed
    print("OK   " if ok else "ECHEC", label)
    failed += (not ok)

root = Path(tempfile.mkdtemp(prefix="i3d_worker_"))   # fait office de racine de l'application (THREEREX_HOME)
data = root / "data"                                   # et de dossier de données (THREEREX_DATA)

fakes = root / "fakes"
(fakes / "torch").mkdir(parents=True)
(fakes / "torch" / "__init__.py").write_text(textwrap.dedent('''
    import os
    float16 = "float16"
    class cuda:
        @staticmethod
        def is_available(): return os.environ.get("FAKE_NO_GPU") != "1"
        @staticmethod
        def get_device_name(i): return "FAKE GPU"
    class Generator:
        def __init__(self, device=None): self.device = device
        def manual_seed(self, seed): self.seed = seed; return self
    __version__ = "0.fake"
'''), encoding="utf-8")
(fakes / "huggingface_hub").mkdir()
(fakes / "huggingface_hub" / "__init__.py").write_text(textwrap.dedent('''
    from pathlib import Path
    def snapshot_download(repo_id, local_dir):
        d = Path(local_dir); d.mkdir(parents=True, exist_ok=True)
        (d / "model_index.json").write_text("{}")
        (d / "calls.txt").write_text(repo_id)
    __version__ = "0.fake"
'''), encoding="utf-8")

pkg = root / "vendor" / "TripoSG" / "triposg" / "pipelines"
pkg.mkdir(parents=True)
(root / "vendor" / "TripoSG" / "triposg" / "__init__.py").write_text("")
(pkg / "__init__.py").write_text("")
(pkg / "pipeline_triposg.py").write_text(textwrap.dedent('''
    from diso import DiffDMC   # doit fonctionner grâce au module factice
    import numpy as np, trimesh

    class _Out:
        def __init__(self, samples): self.samples = samples

    class TripoSGPipeline:
        device = "cuda"
        @classmethod
        def from_pretrained(cls, path):
            assert path.endswith("TripoSG"), path
            return cls()
        def to(self, device, dtype):
            assert device == "cuda" and dtype == "float16"
            return self
        def __call__(self, image, generator, num_inference_steps, guidance_scale, use_flash_decoder,
                     dense_octree_depth, hierarchical_octree_depth, callback_on_step_end):
            assert use_flash_decoder is False, "doit utiliser l'extraction scikit-image"
            assert image.mode == "RGB" and generator.seed == 42 and guidance_scale == 7.0
            for i in range(num_inference_steps):
                out = callback_on_step_end(self, i, 1.0, {"latents": None})
                assert isinstance(out, dict)
            m = trimesh.creation.icosphere(subdivisions=5)
            faces = np.ascontiguousarray(m.faces)[:, ::-1]   # faces à l'envers : le worker doit corriger
            return _Out([(np.asarray(m.vertices, dtype=np.float32), faces)])
'''), encoding="utf-8")

from PIL import Image
Image.new("RGB", (64, 64), "white").save(root / "entree.png")

def run(*args, **env):
    e = dict(os.environ, PYTHONPATH=os.pathsep.join([str(fakes), str(SRC)]), PYTHONIOENCODING="utf-8",
             THREEREX_HOME=str(root), THREEREX_DATA=str(data), **env)
    return subprocess.run([sys.executable, "-u", "-m", "threerex.triposg_worker", *args], cwd=root, env=e,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")

r = run("--image", str(root / "entree.png"), "--out-dir", str(root / "sortie"), "--steps", "4")
print(r.stdout[-600:], r.stderr[-600:])
check("worker : code de sortie 0", r.returncode == 0)
msgs = [l[3:] for l in r.stdout.splitlines() if l.startswith("@@ ")]
check("worker : messages d'avancement (étapes 1/4 à 4/4)", [m for m in msgs if m.startswith("Génération")] == [f"Génération de la forme : étape {i}/4" for i in range(1, 5)])
check("worker : poids téléchargés depuis VAST-AI/TripoSG", (data / "models" / "TripoSG" / "calls.txt").read_text() == "VAST-AI/TripoSG")
import trimesh
full = trimesh.load(str(root / "sortie" / "mesh.ply"), force="mesh")
prev = trimesh.load(str(root / "sortie" / "preview.ply"), force="mesh")
check("worker : mesh.ply et preview.ply écrits", len(full.faces) == 20480 and len(prev.faces) > 0)
check("worker : faces remises à l'endroit (volume positif)", full.volume > 0)
check("worker : aperçu non plus lourd que le maillage complet", len(prev.faces) <= len(full.faces))

# --- allègement + couleurs d'après l'image détourée (disque rouge net -> la sphère doit sortir rouge)
import numpy as np
yy, xx = np.mgrid[0:256, 0:256]
disc = ((xx - 128) ** 2 + (yy - 128) ** 2) < 100 ** 2
rgba = np.zeros((256, 256, 4), np.uint8); rgba[disc] = (220, 30, 30, 255)
Image.fromarray(rgba, "RGBA").save(root / "objet.png")
r = run("--image", str(root / "entree.png"), "--out-dir", str(root / "s3"), "--steps", "2", "--faces", "6000", "--cutout", str(root / "objet.png"))
print(r.stdout[-700:], r.stderr[-500:])
check("allègement + couleurs : code 0", r.returncode == 0)
light = trimesh.load(str(root / "s3" / "mesh.ply"), force="mesh", process=False)
check("allègement : maillage ramené près de 6000 faces", 3000 <= len(light.faces) <= 7000)
col = np.asarray(light.visual.vertex_colors)[:, :3].astype(float)
check("couleurs : la face avant est rouge (couleurs d'après l'image)", np.median(col[:, 0]) > 150 and np.median(col[:, 1]) < 90)
prev3 = trimesh.load(str(root / "s3" / "preview.ply"), force="mesh", process=False)
check("aperçu : couleurs conservées", getattr(prev3.visual, "kind", None) == "vertex" or len(prev3.faces) == len(light.faces))
check("couleurs : message de calage annoncé", any("Couleurs appliquées" in l for l in r.stdout.splitlines()))

Image.fromarray(np.zeros((256, 256, 4), np.uint8), "RGBA").save(root / "vide.png")
r = run("--image", str(root / "entree.png"), "--out-dir", str(root / "s4"), "--steps", "2", "--cutout", str(root / "vide.png"))
check("image détourée vide : la forme est quand même produite", r.returncode == 0 and (root / "s4" / "mesh.ply").exists())
check("image détourée vide : remarque « Couleurs non appliquées »", any(l.startswith("@@NOTE Couleurs non appliquées") for l in r.stdout.splitlines()))

r = run("--image", str(root / "entree.png"), "--out-dir", str(root / "s2"), "--steps", "2", FAKE_NO_GPU="1")
check("sans GPU : code 3 et message @@ERREUR", r.returncode == 3 and "@@ERREUR Aucun GPU CUDA" in r.stdout)

r = run("--check")
print(r.stdout)
check("--check : s'exécute et produit un rapport", r.returncode in (0, 1) and "RESULTAT" in r.stdout and "dépôt TripoSG" in r.stdout)
check("--check : le module factice diso rend l'import possible", "import de TripoSGPipeline (diso remplacé par un module factice)" in r.stdout)

r = run()
check("sans arguments : message d'usage", r.returncode == 2 and "--image" in r.stderr)
print("RESULTAT :", "tout est OK" if failed == 0 else f"{failed} échec(s)")
sys.exit(1 if failed else 0)
