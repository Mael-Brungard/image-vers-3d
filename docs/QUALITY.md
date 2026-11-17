# Qualité des modèles 3D : où on en est, ce qui limite, la suite

Objectif du projet : un logiciel **local, pour un usage personnel**, au résultat le plus proche possible des services comme
Meshy. Ce document dit honnêtement ce qui a été fait, ce qui n'a pas pu être vérifié et comment améliorer ensuite.
Recherches faites le 17 novembre 2026 ; ce domaine change vite.

## Ce que le logiciel propose

| Moteur | Qualité attendue | Vitesse | Mémoire vidéo | Sortie |
|---|---|---|---|---|
| TripoSR (MIT, 2024) | forme approximative, détails mous, couleurs par sommet | quelques secondes | 4 à 6 Go | GLB, OBJ + texture cuite, STL |
| **TRELLIS.2** (Microsoft, MIT, 2025), via trellis.cpp | le plus détaillé des modèles libres utilisables ici : géométrie fine en 1024, matériaux PBR | quelques minutes | voir ci-dessous | GLB texturé PBR, OBJ + texture, STL |

TripoSR n'est plus le meilleur modèle libre : il est gardé comme moteur rapide et de secours. TRELLIS.2 est le moteur « Qualité
maximale ».

## Ce qui limite sur une carte de 12 Go (RTX 4070 Ti)

- TRELLIS.2 officiel (PyTorch) demande 24 Go et Linux. Le portage **trellis.cpp** (C++/GGML, MIT) tourne sous Windows sans Python
  et annonce le 1024 sur une carte de **16 Go** ; il propose des poids quantifiés (« q4 » ≈ 6 Go, « q8 » ≈ 10 Go ; q4 donne une
  texture un peu granuleuse selon ses notes de version). **Aucune mesure sur 12 Go n'est publiée** : le logiciel part en 1024 avec
  les poids q4 et, si la mémoire manque, refait le calcul en 512. Si 1024 échoue chez toi, tu auras un modèle en 512, correct
  mais moins fin.
- Les temps publiés (carte RTX 5060 Ti 16 Go, 1024, 12 étapes) vont de 3 à 7 minutes selon l'image, chargement des modèles compris.
- Le programme est compilé pour CUDA 13 : il faut un pilote NVIDIA 580 ou plus récent.

## Ce qui n'a pas pu être vérifié ici

La machine de développement n'a ni carte NVIDIA ni Windows. Ont été testés : toute la logique du logiciel (téléchargement avec
reprise et vérification, lancement, avancement, repli mémoire, erreurs, export, fenêtre), avec un faux programme à la place de
`trellis-cli.exe`. **Pas testé : le vrai programme, la qualité réelle des modèles, la consommation mémoire réelle sur ta carte,
l'orientation de la sortie** (si l'objet est couché, les boutons « Pivoter » et « Redresser » le corrigent). Les options passées
au programme viennent de l'aide intégrée de la version v0.8.1 (vérifiée sur le fichier téléchargé), pas d'un essai.
Les options ajoutées ensuite (`--res 1536`, `--atlas 4096`, `--tex-res 1024`, poids q8) sont dans cette même aide, mais **leur effet réel
et leur consommation de mémoire sur 12 Go ne sont connus que par essai** : c'est pourquoi elles sont étiquetées « expérimental »
et accompagnées d'un repli automatique.

## Faut-il s'attendre à Meshy ?

Meshy est un service propriétaire (Meshy 6 : textures 2K PBR, remaillage en quadrilatères) ; son modèle n'est pas public et
**aucun comparatif indépendant sérieux face aux modèles libres n'a été trouvé** (les sites de comparaison sont des sources
commerciales sans méthode). Honnêtement : TRELLIS.2 est aujourd'hui ce qui s'en approche le plus parmi les modèles libres, mais
n'attends pas un résultat identique. Le remaillage en quadrilatères propre n'existe pas dans la version Windows de trellis.cpp
(option réservée à Linux). Pour juger toi-même : génère les mêmes cinq images avec TripoSR, TRELLIS.2 Rapide, TRELLIS.2 Détaillé
et Meshy, puis compare le même angle de chaque modèle dans Blender.

## Ce que le logiciel fait pour tirer le maximum (et ce qui reste à toi)

Tout est détaillé, avec l'ordre d'efficacité, dans [IMAGE_DE_DEPART.md](IMAGE_DE_DEPART.md).

| Levier | Où | État |
|---|---|---|
| Image de départ soignée | prompt ChatGPT (page Paramètres), conseils automatiques à l'ouverture d'une image (petite, floue, objet coupé) | fait ; c'est le levier le plus puissant |
| Résolution 1024 / 1536 | qualités Détaillé et Ultra (1536 : expérimental, repli automatique en 1024 puis 512) | fait, 1536 jamais vu sur 12 Go |
| Variantes multiples | « Variantes à comparer » (1 à 4), sélecteur sous le modèle, `_v2` dans le nom du fichier | fait |
| Étapes d'échantillonnage | qualité Maximum (24 au lieu de 12) | fait ; gain faible, non mesuré |
| Précision des poids | « Haute » = q8 (10 Go de plus), téléchargement séparé | fait ; plus de mémoire vidéo |
| Texture très fine | atlas 4096 px + décodage PBR 1024 (`--atlas 4096 --tex-res 1024`) ; repli sur la texture standard si la mémoire manque | fait, expérimental, jamais vu sur 12 Go |
| Détourage | BiRefNet par le moteur ; aperçu « Détourée » | fait |

Gardé à valeurs par défaut du programme faute de pouvoir les mesurer : la force de guidage (`--gss`, `--gsh`), le nombre de
jetons (`--max-tokens`), la largeur de bande du remaillage (`--band`) et la simplification du maillage (300 000 faces en 1024).

## Impression 3D (export STL)

Le format « STL » prépare le modèle pour un logiciel de tranchage (PrusaSlicer, Cura, Lychee, Bambu Studio…). `printing.py` fait,
dans l'ordre : soudure des sommets confondus (un `.glb` en duplique le long des coutures de texture : sans soudure, chacune
serait un « trou »), retrait des faces dégénérées ou en double et des petites poussières flottantes (moins de 0,5 % des faces
**et** moins de 10 % de la taille du modèle : une vraie pièce séparée reste), sens des faces cohérent, **fermeture de chaque
trou par un éventail de triangles**, aplatissement du dessous si besoin, mise à l'échelle à la hauteur demandée et pose sur le
plateau (Z vers le haut). Le rapport affiché après l'enregistrement donne ce qui a été fait et ce qui reste.

- **« Étanche » veut dire surface fermée** : chaque arête est partagée par exactement deux faces. Ce n'est **pas** une garantie
  d'imprimabilité.
- **Non vérifié** : l'épaisseur des parois (plumes, capes, griffes, chevilles fines : le plus souvent la cause d'un échec), les
  auto-intersections, les pièces qui ne se touchent pas (signalées : « N pièces séparées »), les surplombs et les supports.
- **Trous** : un fond plat et convexe redevient plat ; un petit trou se rebouche ; un grand trou irrégulier devient une calotte
  fermée, pas toujours jolie. Une arête partagée par trois faces ou plus ne se répare pas toute seule : le rapport le dit
  (« NON étanche ») et le fichier est quand même écrit, à finir dans PrusaSlicer, Meshmixer ou Blender.
- **Dessous aplati** : coupe au plus 1,5 % de la hauteur, seulement si le bas n'est pas déjà plat (un socle reste intact). Pour une
  figurine sans socle, cela donne une petite surface d'appui, pas un vrai socle ; un socle ajouté dans Blender est plus sûr.
- **Pas de couleurs** : un STL n'en contient pas. Pour une figurine colorée, imprime en une couleur et peins-la, ou garde le GLB
  pour une imprimante multicolore.
- **Testé** : cas synthétiques (sphère trouée, socle sans fond, soupe de triangles de 330 000 faces en 2 à 3 secondes, normales
  inversées, arête partagée par trois faces, poussières), avec trimesh 4.12 (celui de l'installation) et 5.2, et tout le parcours
  de l'interface avec un faux moteur. **Pas testé** : un vrai modèle sorti de TRELLIS.2, ni une vraie impression ; la taille au sol
  annoncée dans la fenêtre est approximative (le dessous aplati la modifie un peu).
- Pour une scène à plusieurs personnages (un enlacement, par exemple), le modèle fusionne ce qui se touche et invente ce que
  l'image cache : mieux vaut un personnage par image, puis les réunir sur un même socle dans Blender.

## Pistes non faites, par ordre d'intérêt

1. **Pixal3D** (MIT) : le programme le gère (`--model pixal3d`), la forme suit mieux l'image de départ. Non intégré : il demande
   cinq fichiers de modèle de plus dont j'ignore la source exacte, et un champ de vision (`--fov`) à régler par image (le programme
   dit que son estimation automatique n'est pas portée : une valeur fausse décale la géométrie par rapport à la silhouette).
2. **Contrôle de l'épaisseur des parois** avant l'impression (alerte sur les zones trop fines) et **socle ajouté automatiquement**.
3. **Carte à 16 ou 24 Go**, ou **GPU loué** (cloud) pour le 1024 en poids complets (f16, 16,5 Go).
4. **Remaillage en quadrilatères** : n'existe pas dans la version Windows du programme (réservé à Linux).

## Modèles écartés

Hunyuan3D 2.x et TripoSG (licence Tencent qui exclut l'Union européenne, même pour un usage personnel), Step1X-3D (27 à 29 Go),
Direct3D-S2 (géométrie seule). Détails : [LICENSES.md](LICENSES.md).
