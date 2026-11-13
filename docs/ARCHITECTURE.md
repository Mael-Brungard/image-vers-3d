# Architecture

## Trois mondes à distinguer

| Monde | Où | Contenu | Survit à une mise à jour ? |
|---|---|---|---|
| Le code | paquet Python `imagevers3d`, installé dans `runtime\main` | interface, génération, export | remplacé |
| La racine de l'application (`APP_ROOT`) | `%LOCALAPPDATA%\Programs\ImageVers3D` (par défaut) | `bin\uv.exe`, `vendor\TripoSR`, `runtime\`, `wheels\`, `setup_runtime.bat`, `licenses\` | remplacée |
| Les données de l'utilisateur (`DATA_DIR`) | `%LOCALAPPDATA%\ImageVers3D` | `logs\`, `models\` (TripoSR, U²-Net), cache de `uv` | conservées |

Tout est résolu à un seul endroit : [`src/imagevers3d/paths.py`](../src/imagevers3d/paths.py). Variables qui prennent le pas
(tests, installations particulières) : `IMAGEVERS3D_HOME`, `IMAGEVERS3D_DATA`, `IMAGEVERS3D_TRIPOSG_PYTHON`.
`paths.configure_environment()` range les modèles téléchargés (`HF_HOME`, `U2NET_HOME`) sous `DATA_DIR\models`.

En développement, `APP_ROOT` est la racine du dépôt (détectée grâce à `pyproject.toml`) et `vendor/` y est créé par
`scripts/fetch_vendor.py`.

## Installation sur l'ordinateur de l'utilisateur

```
ImageVers3D-Setup-x.y.z.exe  (Inno Setup, par utilisateur, sans droits administrateur)
 ├─ copie : bin\uv.exe, vendor\TripoSR, wheels\imagevers3d-*.whl, requirements\windows-py311.lock, scripts .bat, licences
 └─ exécute setup_runtime.bat [cuda|cpu] :
      1. uv python install 3.11          copie privée de Python dans runtime\python (ne touche pas au Python de l'utilisateur)
      2. uv venv runtime\main
      3. uv pip install torch==<version>  depuis l'index CUDA (cu128) ou processeur
      4. uv pip install --require-hashes -r windows-py311.lock   (toutes les autres dépendances, versions et sommes figées)
      5. uv pip install --no-deps imagevers3d-*.whl
      puis  python -m imagevers3d.diagnostic  et écriture de runtime\ready.txt
```

Pourquoi ce choix plutôt qu'un exécutable « tout-en-un » (PyInstaller) : PyTorch avec CUDA pèse plusieurs Go ; le
télécharger à l'installation garde l'installateur léger, permet de réparer sans tout reconstruire et évite les faux
positifs d'antivirus fréquents avec les exécutables gelés. Contrepartie : l'installation demande une connexion Internet.

Les versions épinglées (Python, uv et sa somme SHA-256, PyTorch, commit de TripoSR) sont dans
[`packaging/windows/versions.json`](../packaging/windows/versions.json). Les autres dépendances sont dans
`requirements/main.in` (déclaration) et `requirements/windows-py311.lock` (résolution complète avec sommes de contrôle).

Raccourcis du menu Démarrer : le logiciel (`pythonw.exe -m imagevers3d`, sans fenêtre de console), **Diagnostic**,
**Réparer l'installation** (`setup_runtime.bat cuda repair`) et les licences.

## Le logiciel

| Module | Rôle |
|---|---|
| `launcher.py`, `__main__.py` | point d'entrée ; affiche une boîte de dialogue si le démarrage échoue, journal dans `DATA_DIR\logs` |
| `studio.py` | fenêtre principale (PySide6) : réglages, états du visualiseur, visionneuse 3D (pyqtgraph + OpenGL), tâches en arrière-plan, export |
| `theme.py` | système de design : jetons de couleur (copie de `design/tokens.json`), feuille de style Qt, thème sombre/clair/système, échelle du texte, mouvement réduit |
| `widgets.py` | composants : interrupteur, contrôle segmenté, zone de dépôt, notification, panneau d'erreur, menu Réglages, états vide et calcul |
| `icons.py` | icônes Lucide (SVG) colorées par le thème |
| `image_to_3d.py` | pipeline TripoSR : retrait du fond (rembg, modèle `u2net` nommé explicitement), inférence, extraction du maillage, export |
| `mcubes_fallback.py` | remplaçant de `torchmcubes` (extension C++ à compiler) fondé sur scikit-image |
| `mesh_tools.py` | nettoyage (fragments flottants, normales), allègement, projection de couleurs, export GLB/OBJ/PLY sans métadonnées locales |
| `geometry.py` | conventions d'orientation : repère de TripoSR (Z vers le haut), repère de l'export (Y vers le haut) et de la visionneuse |
| `license.py`, `_licproto.py`, `_ed25519.py`, `_license_keys.py` | licence : état, activation, essai, jetons signés, clés publiques ; **compilés** dans la version commerciale ([LICENSING.md](LICENSING.md)) |
| `license_ui.py` | écran Licence, pastille d'essai |
| `diagnostic.py` | vérification de l'installation, lancée par l'installateur et par le raccourci |
| `paths.py` | tous les emplacements de fichiers |
| `triposg_runner.py`, `triposg_worker.py`, `shims/diso` | moteur TripoSG **désactivé** (voir plus bas) |

### Orientation

TripoSR travaille en Z vers le haut, avant du modèle vers +X. L'export (GLB/OBJ) est en Y vers le haut, avant vers +Z :
rotation `Ry(−90°) @ Rx(−90°)` (déterminant +1, donc pas de miroir). La visionneuse applique la rotation inverse pour afficher
dans son propre repère. Ces conventions sont verrouillées par `tests/scenarios/orientation.py`.

### Couleurs et export

Les couleurs de sommets restent en sRGB dans les fichiers PLY/OBJ ; elles sont converties en linéaire uniquement à l'export
GLB (`COLOR_0` est linéaire dans glTF). Budget de faces : 150 000 pour l'aperçu, 400 000 pour l'export (`fast_simplification`).

### Moteur TripoSG désactivé

Le code d'un second moteur (TripoSG : forme plus fine, couleurs projetées depuis l'image) est conservé mais **n'est ni
installé ni distribué** : le dépôt TripoSG embarque une licence Tencent (code dérivé de HunyuanDiT) qui exclut l'Union européenne
([LICENSES.md](LICENSES.md#triposg-exclu)). L'interface ne propose le moteur que s'il est détecté dans `runtime\triposg`. Il
tourne dans un processus séparé (`python -m imagevers3d.triposg_worker`) dont la sortie suit un protocole simple : lignes
`@@ message` (avancement), `@@NOTE message` (remarque finale), `@@ERREUR message` + code de sortie 3 (erreur lisible).

## Licences et serveur

Le logiciel vérifie un jeton signé, hors ligne ; le serveur (`server/`, déployé à part) est le seul à pouvoir le signer. Fichier
d'état : `DATA_DIR\license.json`. Détails, limites et construction d'une version commerciale : [LICENSING.md](LICENSING.md) ;
installation et exploitation du serveur : [SERVER.md](SERVER.md).

## Tests

Voir [DEVELOPMENT.md](DEVELOPMENT.md). Les scénarios de bout en bout simulent le moteur d'IA (faux `torch`, faux TripoSG) pour
tourner partout ; ils vérifient l'orientation, l'export, l'interface, l'absence de console sous `pythonw`, le protocole du
processus de calcul, et les garde-fous de licence.
