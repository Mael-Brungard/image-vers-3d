"""Simule pythonw.exe : stdout et stderr valent None au moment de l'import de imagevers3d.studio."""
import os, subprocess, sys, tempfile, textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
data = Path(tempfile.mkdtemp(prefix="i3d_pythonw_"))

code = textwrap.dedent(f"""
    import sys
    sys.stdout = None
    sys.stderr = None
    sys.path.insert(0, {str(SRC)!r})
    from imagevers3d import studio
    assert sys.stdout is not None and sys.stderr is not None, "redirection absente"
    print("print ok")
    sys.stderr.write("stderr ok\\n")
    try:
        from tqdm import tqdm
        for _ in tqdm(range(3)):
            pass
        tq = "tqdm ok"
    except ImportError:
        tq = "tqdm absent"
    print(tq)
    import logging
    logging.getLogger("x").warning("warn ok")
""")
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", IMAGEVERS3D_DATA=str(data))
r = subprocess.run([sys.executable, "-I", "-c", code], cwd=data, env=env, capture_output=True, text=True)
print("code retour :", r.returncode)
print("stderr du processus :", r.stderr.strip()[-400:])
log = data / "logs" / "studio_console.log"
print("studio_console.log existe :", log.exists())
if log.exists():
    print(log.read_text(encoding="utf-8"))
ok = r.returncode == 0 and log.exists() and "print ok" in log.read_text(encoding="utf-8")
print("RESULTAT :", "OK" if ok else "ECHEC")
sys.exit(0 if ok else 1)
