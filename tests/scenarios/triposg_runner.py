"""Teste triposg_runner (lancement du worker, avancement, erreurs) avec de faux workers."""
import sys, tempfile, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from PIL import Image
from threerex.triposg_runner import TripoSGRunner, venv_python

failed = 0
def check(label, ok):
    global failed
    print("OK   " if ok else "ECHEC", label)
    failed += (not ok)

root = Path(tempfile.mkdtemp())
(root / "vendor" / "TripoSG").mkdir(parents=True)
img = Image.new("RGB", (64, 64), "white")

def make_worker(body):
    p = root / "fake_worker.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p

# --- worker qui réussit
ok_worker = make_worker('''
    import argparse, sys
    from pathlib import Path
    import trimesh
    ap = argparse.ArgumentParser()
    ap.add_argument("--image"); ap.add_argument("--out-dir"); ap.add_argument("--steps"); ap.add_argument("--seed"); ap.add_argument("--cutout")
    a = ap.parse_args()
    from PIL import Image
    assert Image.open(a.image).size == (64, 64)
    print("@@ Chargement…", flush=True)
    if a.cutout:
        assert Image.open(a.cutout).mode == "RGBA"
        print("@@NOTE Couleurs : ajustement moyen.", flush=True)
    print(f"seed={a.seed}", flush=True)
    print("barre de progression\\rqui utilise des retours chariot", flush=True)
    for i in range(3):
        print(f"@@ étape {i+1}/{a.steps}", flush=True)
    out = Path(a.out_dir); out.mkdir(parents=True)
    full = trimesh.creation.icosphere(subdivisions=4); full.export(str(out / "mesh.ply"))
    trimesh.creation.icosphere(subdivisions=1).export(str(out / "preview.ply"))
''')
runner = TripoSGRunner(root=root, python=Path(sys.executable), worker=ok_worker)
check("disponible quand python, worker et dépôt existent", runner.available())
messages = []
preview, full, notes = runner.generate(img, 7, messages.append)
check("messages d'avancement relayés (sans le bruit)", messages == ["Chargement…", "étape 1/7", "étape 2/7", "étape 3/7"])
check("sans image détourée : aucune remarque", notes == [])
preview, full, notes = runner.generate(img, 7, lambda m: None, seed=11, cutout=Image.new("RGBA", (64, 64), (0, 0, 0, 0)))
check("image détourée transmise au worker et remarque relayée", notes == ["Couleurs : ajustement moyen."])
check("métadonnées du fichier effacées", "file_path" not in full.metadata and "file_path" not in preview.metadata)
check("aperçu plus léger que le maillage complet", len(preview.faces) < len(full.faces) and len(full.faces) > 1000)
check("dossier temporaire nettoyé", not list(Path(tempfile.gettempdir()).glob("triposg_*")))

# --- erreur voulue du worker
user_err = make_worker('''
    import sys
    print("@@ début", flush=True)
    print("@@ERREUR Aucun GPU CUDA détecté.", flush=True)
    sys.exit(3)
''')
try:
    TripoSGRunner(root=root, python=Path(sys.executable), worker=user_err).generate(img, 5, lambda m: None)
    check("erreur voulue propagée", False)
except RuntimeError as exc:
    check("erreur voulue propagée telle quelle", str(exc) == "Aucun GPU CUDA détecté.")
    check("sortie du worker jointe aux détails", exc.__cause__ is not None)

# --- plantage avec trace
crash = make_worker('''
    raise ModuleNotFoundError("No module named 'triposg'")
''')
try:
    TripoSGRunner(root=root, python=Path(sys.executable), worker=crash).generate(img, 5, lambda m: None)
    check("plantage signalé", False)
except RuntimeError as exc:
    check("plantage : message avec la dernière ligne", "ModuleNotFoundError" in str(exc) and "Diagnostic" in str(exc))
    check("plantage : trace complète dans la cause", "Traceback" in str(exc.__cause__))

# --- mémoire GPU
oom = make_worker('''
    import sys
    sys.stderr.write("torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB\\n")
    sys.exit(1)
''')
try:
    TripoSGRunner(root=root, python=Path(sys.executable), worker=oom).generate(img, 5, lambda m: None)
    check("OOM signalé", False)
except RuntimeError as exc:
    check("mémoire GPU : message clair", "Mémoire GPU insuffisante" in str(exc))

# --- worker qui n'écrit rien
silent = make_worker('print("ok mais rien produit")')
try:
    TripoSGRunner(root=root, python=Path(sys.executable), worker=silent).generate(img, 5, lambda m: None)
    check("sortie absente signalée", False)
except RuntimeError as exc:
    check("aucun fichier produit : message", "aucun fichier" in str(exc))

# --- non installé
missing = TripoSGRunner(root=root / "inexistant")
check("non disponible si rien n'est installé", not missing.available())
try:
    missing.generate(img, 5, lambda m: None)
    check("erreur claire si non installé", False)
except RuntimeError as exc:
    check("erreur claire si non installé", "TripoSG" in str(exc) and "TripoSR" in str(exc))
check("chemin du python de l'environnement", str(venv_python(Path("/x"))).replace("\\", "/") in ("/x/runtime/triposg/bin/python", "/x/runtime/triposg/Scripts/python.exe"))
print("RESULTAT :", "tout est OK" if failed == 0 else f"{failed} échec(s)")
sys.exit(1 if failed else 0)
