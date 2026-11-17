# Architecture

## Trois mondes à distinguer

| Monde | Où | Contenu | Survit à une mise à jour ? |
|---|---|---|---|
| Le code | paquet Python `threerex`, installé dans `runtime\main` | interface, génération, export | remplacé |
| La racine de l'application (`APP_ROOT`) | `%LOCALAPPDATA%\Programs\ThreeRex` (par défaut) | `bin\uv.exe`, `vendor\TripoSR`, `runtime\`, `wheels\`, `setup_runtime.bat`, `licenses\` | remplacée |
| Les données de l'utilisateur (`DATA_DIR`) | `%LOCALAPPDATA%\ThreeRex` | `logs\`, `models\` (TripoSR, U²-Net), `engines\`, `creations\`, cache de `uv` | conservées |

Tout est résolu à un seul endroit : [`src/threerex/paths.py`](../src/threerex/paths.py). Variables qui prennent le pas
(tests, installations particulières) : `THREEREX_HOME`, `THREEREX_DATA`, `THREEREX_TRIPOSG_PYTHON`.
`paths.configure_environment()` range les modèles téléchargés (`HF_HOME`, `U2NET_HOME`) sous `DATA_DIR\models`.

En développement, `APP_ROOT` est la racine du dépôt (détectée grâce à `pyproject.toml`) et `vendor/` y est créé par
`scripts/fetch_vendor.py`.

## Installation sur l'ordinateur de l'utilisateur

```
ThreeRex-Setup-x.y.z.exe  (Inno Setup, par utilisateur, sans droits administrateur)
 ├─ copie : bin\uv.exe, vendor\TripoSR, wheels\threerex-*.whl, requirements\windows-py311.lock, scripts .bat, licences
 └─ exécute setup_runtime.bat [cuda|cpu] :
      1. uv python install 3.11          copie privée de Python dans runtime\python (ne touche pas au Python de l'utilisateur)
      2. uv venv runtime\main
      3. uv pip install torch==<version>  depuis l'index CUDA (cu128) ou processeur
      4. uv pip install --require-hashes -r windows-py311.lock   (toutes les autres dépendances, versions et sommes figées)
      5. uv pip install --no-deps threerex-*.whl
      puis  python -m threerex.diagnostic  et écriture de runtime\ready.txt
```

Pourquoi ce choix plutôt qu'un exécutable « tout-en-un » (PyInstaller) : PyTorch avec CUDA pèse plusieurs Go ; le
télécharger à l'installation garde l'installateur léger, permet de réparer sans tout reconstruire et évite les faux
positifs d'antivirus fréquents avec les exécutables gelés. Contrepartie : l'installation demande une connexion Internet.

Les versions épinglées (Python, uv et sa somme SHA-256, PyTorch, commit de TripoSR) sont dans
[`packaging/windows/versions.json`](../packaging/windows/versions.json). Les autres dépendances sont dans
`requirements/main.in` (déclaration) et `requirements/windows-py311.lock` (résolution complète avec sommes de contrôle).

Raccourcis du menu Démarrer : le logiciel (`pythonw.exe -m threerex`, sans fenêtre de console), **Diagnostic**,
**Réparer l'installation** (`setup_runtime.bat cuda repair`) et les licences.

## Le logiciel

| Module | Rôle |
|---|---|
| `launcher.py`, `__main__.py` | point d'entrée ; affiche une boîte de dialogue si le démarrage échoue, journal dans `DATA_DIR\logs` |
| `studio.py` | fenêtre principale (PySide6) : onglets, panneau de réglages, état de l'application (tâche, résultat, variantes, erreur), assistant, plein écran, tâches en arrière-plan, export ; moteur d'IA (`Engine`) |
| `viewport.py` | visualiseur : `MeshViewer` (pyqtgraph + OpenGL, modes pivoter / déplacer / zoom), `ViewportFrame` (pages vide, calcul, résultat, erreur et leurs calques), transition image → modèle |
| `fx.py` | identité et animations : horloge unique, mascotte T-Rex et logo vectoriels, robot assistant, panneaux angulaires, bouton lumineux, puces, onglets, particules, reconstruction animée, bulle, séparateur redimensionnable |
| `pages.py` | pages « Mes créations » (cartes) et « Paramètres » |
| `creations.py` | liste de « Mes créations » (JSON atomique + vignettes dans `DATA_DIR\creations`) ; retirer une entrée ne supprime jamais le fichier |
| `theme.py` | système de design : jetons de couleur (copie de `design/tokens.json`), feuille de style Qt, thème sombre unique, échelle du texte, mouvement réduit et effets visuels |
| `widgets.py` | composants : interrupteur, contrôle segmenté, zone de dépôt, notification, panneau d'erreur, pastille du calcul, états vide et calcul |
| `icons.py` | icônes Lucide (SVG) colorées par le thème |
| `image_to_3d.py` | pipeline TripoSR : retrait du fond (rembg, modèle `u2net` nommé explicitement), inférence, extraction du maillage, export |
| `mcubes_fallback.py` | remplaçant de `torchmcubes` (extension C++ à compiler) fondé sur scikit-image |
| `mesh_tools.py` | nettoyage (fragments flottants, normales), allègement, projection de couleurs, export GLB/OBJ/PLY sans métadonnées locales |
| `printing.py` | préparation à l'impression 3D, fonctions pures (sans Qt ni PyTorch) : soudure des sommets, nettoyage, sens des faces, fermeture des trous par éventails, aplatissement du dessous, échelle en mm (Z en haut, posé sur Z = 0), STL binaire, `PrintReport` |
| `print_dialog.py` | fenêtre « Impression 3D » : hauteur et aplatissement, avec la taille au sol annoncée d'après les proportions du modèle |
| `geometry.py` | conventions d'orientation : repère de TripoSR (Z vers le haut), repère de l'export (Y vers le haut) et de la visionneuse |
| `diagnostic.py` | vérification de l'installation, lancée par l'installateur et par le raccourci |
| `paths.py` | tous les emplacements de fichiers |
| `trellis_runner.py` | moteur « Qualité maximale » : téléchargement du programme et des poids, lancement, repli mémoire, export |
| `triposg_runner.py`, `triposg_worker.py`, `shims/diso` | moteur TripoSG **désactivé** (voir plus bas) |

### Interface : qui décide de quoi

`MainWindow` est la seule à connaître l'état (image, tâche en cours, résultat, variantes, erreur) ; `MainWindow._refresh_ui()`
en déduit tout l'affichage (boutons actifs, page du visualiseur, texte du bouton principal, bulle de l'assistant, barre de
progression). Les composants de `fx.py`, `widgets.py` et `viewport.py` n'ont pas d'état d'application : ils reçoivent des
valeurs et émettent des signaux. Les tâches longues passent par `Task` (QRunnable, une seule à la fois) ; le résultat revient
par signal dans le fil de l'interface.

- Un test (`tests/scenarios/studio_ui.py`) pilote la vraie fenêtre avec un moteur factice ; un second
  (`tests/scenarios/layout_audit.py`) vérifie la mise en page à plusieurs tailles (voir [DESIGN.md](DESIGN.md#responsive)).
- Au premier lancement après le renommage, `migrate_legacy_settings` reprend les réglages de « Image vers 3D » et
  `paths.migrate_legacy_data` déplace l'ancien dossier de données (modèles déjà téléchargés compris).

### Orientation

TripoSR travaille en Z vers le haut, avant du modèle vers +X. L'export (GLB/OBJ) est en Y vers le haut, avant vers +Z :
rotation `Ry(−90°) @ Rx(−90°)` (déterminant +1, donc pas de miroir). La visionneuse applique la rotation inverse pour afficher
dans son propre repère. Ces conventions sont verrouillées par `tests/scenarios/orientation.py`.

### Couleurs et export

Les couleurs de sommets restent en sRGB dans les fichiers PLY/OBJ ; elles sont converties en linéaire uniquement à l'export
GLB (`COLOR_0` est linéaire dans glTF). Budget de faces : 150 000 pour l'aperçu, 400 000 pour l'export (`fast_simplification`).

### Moteur « Qualité maximale » (TRELLIS.2 via trellis.cpp)

`trellis_runner.py` ne dépend ni de PyTorch ni de Qt. Au premier usage (bouton « Installer le moteur »), il télécharge sous
`%LOCALAPPDATA%\ThreeRex\engines\trellis` : le programme `trellis-cli.exe` (archive GitHub épinglée, somme SHA-256 vérifiée,
CUDA 13) puis les dix fichiers GGUF « q4 » de `ilintar/trellis2-gguf` sur Hugging Face (6,5 Go ; somme de chaque fichier lue dans
l'en-tête `X-Linked-ETag`). Les téléchargements reprennent là où ils se sont arrêtés. Le calcul tourne dans un processus séparé
(`trellis-cli.exe image.png sortie.glb --models … --res 512|1024 --steps N --seed N --bg-removal … --webp off --require-gpu`) ;
la sortie est lue ligne à ligne pour l'avancement, plus un chronomètre. Un manque de mémoire vidéo en 1024 relance le calcul en
512 ; un échec du pilote ou de la carte donne un message qui renvoie à la mise à jour du pilote. Le `.glb` obtenu est gardé en
mémoire : « Enregistrer » le recopie à l'identique (texture PBR intacte) ou, après « Pivoter / Redresser » ou en `.obj`, le réécrit
avec trimesh. La visionneuse reçoit une copie à couleurs par sommet tirées de la texture. Variables : `THREEREX_TRELLIS_QUANT`
(`q4` par défaut, `q8` ≈ 10 Go), `THREEREX_TRELLIS_EXE` (programme de remplacement). Les options passées au programme ont été
relevées dans la version v0.8.1 (en particulier, elle n'a pas d'option `--faces`) : changer `RELEASE_TAG` impose de les revérifier.

Garde-fous (issus d'une relecture indépendante) :

- **Installation** : le programme va dans `program-<version>` (un dossier par version, extrait d'abord dans un dossier `.tmp` puis
  renommé), puis `trellis-cli.exe --help` est lancé pour vérifier qu'il démarre (DLL absente, antivirus) *avant* les 6,5 Go de poids ;
  en cas d'échec le dossier est retiré mais l'archive est gardée et réutilisée à l'essai suivant. Les poids sont épinglés à une
  révision de Hugging Face (`WEIGHTS_REVISION`). Le moteur n'est proposé que si un pilote NVIDIA est détecté (`nvcuda.dll`).
- **Chemins** : le programme est lancé depuis `engines\trellis` avec des chemins relatifs ASCII (`work\tXXXX\entree.png`,
  `models\q4`) : un nom d'utilisateur Windows avec accents ne peut pas le gêner. Les dossiers de travail y sont aussi (et
  nettoyés après 6 h s'ils ont survécu à un arrêt brutal).
- **Arrêt** : `cancel_all()` (appelé à la fermeture de la fenêtre et à la sortie du processus) interrompt téléchargements et
  calcul ; le processus enfant est tué, la carte graphique libérée. Un délai de 45 minutes arrête un calcul qui ne finit pas.
- **Mémoire vidéo** : avant de lancer TRELLIS.2, `Engine._release_gpu()` décharge TripoSR (rechargé à la demande).
- **Erreurs** : manque de mémoire et pilote sont détectés pendant tout le calcul (pas seulement dans la fin du journal), en
  ignorant les lignes « retrying » du programme ; les codes de sortie Windows d'un programme qui n'a pas pu démarrer donnent un
  message dédié ; `SetErrorMode` évite la boîte de dialogue bloquante d'une DLL manquante.

Leviers de qualité :

- **Échelle de repli** (`TrellisRunner._ladder`) : si la mémoire vidéo manque, texture très fine → texture standard, puis 1536 →
  1024 → 512 ; chaque repli est noté dans la ligne d'état. Un autre type d'échec (pilote, plantage) n'entraîne pas de repli.
- **Texture très fine** = `--atlas 4096 --tex-res 1024` (par défaut le programme prend 2048 px et décide seul du décodage PBR).
- **Précision des poids** : `set_quant("q4"|"q8")` change le dossier `models/<quant>` ; chaque précision se télécharge à part.
- **Variantes** : la tâche de génération (studio.py) appelle le moteur avec les numéros `seed`, `seed+1`… ; si une variante
  échoue après la première, les précédentes sont gardées et le problème est signalé. `MainWindow.variants` contient un résultat
  par variante, `MainWindow.result` celle qui est affichée ; « Pivoter » et « Redresser » valent pour toutes.
- **Conseils sur l'image** (`image_checks.py`, sans Qt) : taille, netteté relative (contour le plus net / contraste, à 512 px) et
  objet touchant le bord (mesure sur un fond uni jugé d'après les quatre coins, ou d'après la transparence). Seuils prudents :
  en cas de doute, rien n'est affiché. Le même module porte le prompt d'image (`IMAGE_PROMPT`), identique à celui de
  `docs/IMAGE_DE_DEPART.md` (test de cohérence).

### Moteur TripoSG désactivé

Le code d'un second moteur (TripoSG : forme plus fine, couleurs projetées depuis l'image) est conservé mais **n'est ni
installé ni distribué** : le dépôt TripoSG embarque une licence Tencent (code dérivé de HunyuanDiT) qui exclut l'Union européenne
([LICENSES.md](LICENSES.md#triposg-exclu)). L'interface ne propose le moteur que s'il est détecté dans `runtime\triposg`. Il
tourne dans un processus séparé (`python -m threerex.triposg_worker`) dont la sortie suit un protocole simple : lignes
`@@ message` (avancement), `@@NOTE message` (remarque finale), `@@ERREUR message` + code de sortie 3 (erreur lisible).

## Tests

Voir [DEVELOPMENT.md](DEVELOPMENT.md). Les scénarios de bout en bout simulent le moteur d'IA (faux `torch`, faux TripoSG) pour
tourner partout ; ils vérifient l'orientation, l'export, l'interface, l'absence de console sous `pythonw`, le protocole du
processus de calcul, et les garde-fous de licence.
