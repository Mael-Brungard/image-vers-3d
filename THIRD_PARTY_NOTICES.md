# Composants tiers et licences

ThreeRex s'appuie sur des composants libres et sur des modèles d'IA publiés par d'autres. Chacun reste soumis à sa
propre licence, rappelée ci-dessous. Les textes complets sont disponibles aux adresses indiquées et, pour les paquets
Python, dans leurs dossiers d'installation (`runtime\main\Lib\site-packages\<paquet>.dist-info`).

Le logiciel n'embarque et ne télécharge **pas** TripoSG, Hunyuan3D, RMBG-2.0 / BRIA RMBG, FLUX ni `pymeshlab` : leurs licences
excluent l'Union européenne, l'usage commercial, ou imposent la GPL (voir `docs/LICENSES.md` du dépôt).

## Modèles d'IA (téléchargés au premier usage)

| Modèle | Rôle | Licence indiquée | Source |
|---|---|---|---|
| TripoSR (`stabilityai/TripoSR`) | image vers 3D | MIT | https://huggingface.co/stabilityai/TripoSR |
| DINO ViT-B/16 (`facebook/dino-vitb16`) | lecture de l'image, utilisée par TripoSR | Apache-2.0 | https://huggingface.co/facebook/dino-vitb16 |
| U²-Net (`u2net`, via rembg) | retrait du fond | Apache-2.0 (dépôt) | https://github.com/xuebinqin/U-2-Net |
| TRELLIS.2-4B (Microsoft), conversion GGUF `ilintar/trellis2-gguf` | image vers 3D avec textures PBR (moteur « Qualité maximale ») | MIT (modèle d'origine) ; la page de la conversion indique « other » : voir le modèle d'origine | https://github.com/microsoft/TRELLIS.2 · https://huggingface.co/ilintar/trellis2-gguf |
| BiRefNet (inclus dans la conversion ci-dessus) | retrait du fond du moteur « Qualité maximale » | MIT | https://github.com/ZhengPeng7/BiRefNet |
| DINOv3 (Meta, inclus dans la conversion ci-dessus) | lecture de l'image par le moteur « Qualité maximale » | licence propre à Meta (« DINOv3 License ») : à lire avant tout usage autre que personnel | https://github.com/facebookresearch/dinov3 |

Le moteur « Qualité maximale » (TRELLIS.2) est téléchargé à la demande de l'utilisateur, jamais embarqué dans l'installateur.

Remarques sur TripoSR : sa page demande de ne pas l'utiliser pour créer intentionnellement des modèles 3D que l'on jugerait
raisonnablement choquants ou qui véhiculent des stéréotypes (règle à respecter). Son jeu
d'entraînement s'appuie sur un sous-ensemble d'Objaverse publié sous CC-BY.

## Code distribué avec le logiciel

| Composant | Licence | Source |
|---|---|---|
| TripoSR (dossier `vendor/TripoSR`, commit épinglé) | MIT (certains fichiers : Apache-2.0, © HuggingFace) | https://github.com/VAST-AI-Research/TripoSR |
| uv (dossier `bin`) | MIT ou Apache-2.0, au choix | https://github.com/astral-sh/uv |

## Programme téléchargé au premier usage du moteur « Qualité maximale »

| Composant | Licence | Source |
|---|---|---|
| trellis.cpp v0.8.1 (`trellis-cli.exe` et bibliothèques GGML/CUDA qui l'accompagnent), version épinglée et vérifiée par somme SHA-256 | MIT (code) ; les bibliothèques NVIDIA CUDA qui l'accompagnent (cudart, cuBLAS) sont sous licence NVIDIA | https://github.com/pwilkin/trellis.cpp |

## Ressources d'interface (incluses dans le paquet Python du logiciel)

| Ressource | Usage | Licence | Source |
|---|---|---|---|
| Inter (graisses Regular, Medium, SemiBold) | police de l'interface | SIL Open Font License 1.1 (`Inter-OFL.txt`) | https://github.com/rsms/inter |
| Lucide (39 icônes dessinées en SVG) | icônes de l'interface | ISC, avec une part issue de Feather sous MIT (`Lucide-ISC.txt`) | https://lucide.dev |

La police est livrée telle que publiée, sans modification ni vente séparée, ce que la licence OFL autorise. L'icône de l'application
et le globe d'accueil sont des créations originales de ce projet.

## Bibliothèques installées dans `runtime\main`

| Composant | Licence |
|---|---|
| Python (copie gérée par uv) | PSF-2.0 |
| PyTorch | BSD-3-Clause |
| Bibliothèques CUDA fournies par PyTorch (`nvidia-*`) | licences NVIDIA : téléchargées depuis l'index PyTorch sur l'ordinateur de l'utilisateur, non redistribuées par ce logiciel |
| PySide6 / Qt for Python (+ Qt) | LGPL-3.0 (voir plus bas) |
| pyqtgraph | MIT |
| PyOpenGL | BSD |
| numpy, scipy, scikit-image | BSD-3-Clause |
| trimesh | MIT |
| Pillow | HPND (permissive) |
| fast-simplification | MIT |
| rembg | MIT |
| onnxruntime | MIT |
| numba, llvmlite | BSD-2-Clause |
| pymatting | MIT |
| opencv-python-headless | Apache-2.0 (embarque FFmpeg, sous LGPL) |
| transformers, huggingface_hub, safetensors, tokenizers | Apache-2.0 |
| einops, imageio, xatlas, moderngl, glcontext | MIT / BSD |
| omegaconf | BSD-3-Clause |
| tqdm | MPL-2.0 et MIT |

La liste exacte (versions comprises) et la licence déclarée par chaque paquet sont produites à chaque version par
`scripts/licences_report.py` ; le rapport est joint aux artefacts de publication.

## PySide6 (LGPL v3)

Ce logiciel utilise PySide6 (Qt for Python) sous licence GNU LGPL v3. PySide6 est installé comme bibliothèque séparée, dans
le dossier `runtime\main` de l'application : il peut être remplacé par une autre version compatible (`runtime\main\Scripts\python
-m pip install PySide6==<version>`). Texte de la licence : https://www.gnu.org/licenses/lgpl-3.0.html. Code source de
PySide6 : https://code.qt.io/cgit/pyside/pyside-setup.git/ ; code source de Qt : https://code.qt.io/cgit/qt/
