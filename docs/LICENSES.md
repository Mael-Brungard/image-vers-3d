# Licences : audit et décisions

> Ceci est un état des lieux technique, **pas un avis juridique**.
> Pages officielles et fichiers de licence consultés le **6 novembre 2026** ; les licences peuvent changer ensuite.

## Usage personnel (situation actuelle)

Depuis le 17 novembre 2026 le logiciel n'est plus destiné à être vendu : il sert à son auteur, en local, sur son propre
ordinateur. Cela change ce qui est permis, mais pas tout :

- **Les licences « non commerciales » (CC BY-NC, recherche seule…) autorisent un usage personnel et non lucratif.** Les modèles
  qui étaient écartés *uniquement* pour cette raison (RMBG-2.0, FLUX.1 Kontext [dev]…) redeviennent utilisables ici. Les
  objets imprimés pour soi, offerts ou exposés sans contrepartie restent dans ce cadre ; **dès qu'on vend les modèles 3D, les
  figurines ou le logiciel, ces licences ne couvrent plus rien.** Marque-les dans le code pour ne pas l'oublier.
- **Les licences qui excluent l'Union européenne (Tencent : Hunyuan3D, TripoSG) restent exclues**, même pour un usage personnel :
  elles interdisent d'*utiliser* le modèle ou ses résultats dans l'Union, pas seulement de le vendre.
- Les licences GPL/AGPL ne gênent pas un usage purement personnel (rien n'est distribué), mais elles reviennent dès qu'on
  partage l'installateur ou le code.

Choisir de préférence des modèles MIT ou Apache-2.0 reste la voie qui laisse la porte ouverte à la vente de figurines plus tard :
on n'utilise un modèle « non commercial » que si le gain de qualité est net, et on le dit dans l'interface et dans ce fichier.

## Résumé des décisions

| Composant | Décision | Raison |
|---|---|---|
| TripoSR (code et poids) | **utilisé**, distribué (code) / téléchargé (poids) | MIT |
| TRELLIS.2 (Microsoft) via trellis.cpp | **utilisé** (moteur « Qualité maximale »), téléchargé à la demande | MIT (modèle et programme) ; BiRefNet MIT ; DINOv3 : licence propre à Meta ; conversion GGUF : « other » sur Hugging Face, voir le modèle d'origine |
| rembg + modèle `u2net` | **utilisé** ; le modèle est nommé explicitement dans le code | le modèle par défaut des rembg récents est non commercial (voir plus bas) |
| PySide6 (Qt) | **utilisé**, en bibliothèque séparée | LGPL-3.0 : obligations à respecter (voir plus bas) |
| TripoSG | **exclu** (code conservé, désactivé) | licence Tencent qui exclut l'Union européenne (voir plus bas) |
| RMBG-2.0 / `bria-rmbg` | **autorisé pour usage personnel seulement** (pas encore utilisé) | CC BY-NC 4.0 : non commercial |
| Hunyuan3D 2.x | **exclu** | licence qui exclut l'Union européenne |
| FLUX.1 Kontext [dev], FLUX.2 klein 9B | usage personnel seulement (pas encore utilisés) | non commerciaux |
| `pymeshlab` | **exclu** | GPL |
| `imageio-ffmpeg` | **exclu** (on installe `imageio` seul) | embarque un binaire ffmpeg sous GPL |
| `gradio` (interface web de TripoSR) | **exclu** | inutile ici ; dépendances nombreuses |

Les garde-fous automatiques : `tests/test_license_guard.py` (modèle de détourage nommé, composants exclus absents des
dépendances) et `tests/test_packaging.py` (le verrou ne contient pas ces paquets ; seul TripoSR est embarqué).

## TripoSG exclu

La page Hugging Face de TripoSG indique la licence MIT, et le fichier `LICENSE` du dépôt est bien MIT. Mais :

- `triposg/models/transformers/triposg_transformer.py` indique : « Portions of this code are copied or adapted from
  HunyuanDiT » et reproduit en en-tête la **Tencent Hunyuan Community License Agreement**. Ce texte dit : « THIS LICENSE
  AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION », définit le « Territory » comme « the worldwide territory, excluding the
  territory of the European Union », limite la distribution au Territory, et interdit d'utiliser ou d'afficher « the Tencent
  Hunyuan Works, Output or results of the Tencent Hunyuan Works outside the Territory ».
- Le fichier `NOTICE` du dépôt cite aussi du code dérivé de FlashVDM (licence communautaire Tencent) et RMBG-1.4 (licence
  `bria-rmbg-1.4`, non commerciale, utilisée par les scripts d'exemple).

Conséquence : distribuer TripoSG dans un logiciel vendu depuis l'Union européenne, ou l'utiliser depuis l'Union, n'est pas couvert par
la licence MIT affichée. Le logiciel ne l'embarque donc pas et ne le télécharge pas. Le code d'intégration reste dans le dépôt
(désactivé) pour le cas où une version future retirerait ces dépendances ou si un accord était obtenu auprès de Tencent.

**À faire :** demander un avis juridique sur les figurines ou fichiers déjà produits avec TripoSG (la clause vise aussi les
« Output »).

## rembg et le modèle de détourage

`rembg` 2.0.87 prend par défaut le modèle `bria-rmbg` (RMBG-2.0, CC BY-NC 4.0). Le code appelle donc toujours
`rembg.new_session("u2net")` (constante `REMBG_MODEL` dans `image_to_3d.py`), et un test refuse tout appel sans modèle nommé.

U²-Net : dépôt sous Apache-2.0 ; la licence des **poids** n'est pas indiquée séparément (point à confirmer). Alternatives
vérifiées sur leurs pages : BiRefNet (MIT) ; IS-Net / DIS (Apache-2.0, poids non précisés). Benchmark sur une image de créature
(IoU contre un détourage de référence, fonds variés) : `u2net` 0,87 à 0,97 selon le fond ; `isnet-general-use` meilleur sur fond
uni (0,96) mais s'effondre sur fonds gris ou chargés (0,51 à 0,54). BiRefNet n'a pas pu être mesuré (mémoire insuffisante sur la
machine d'essai) : à tester sur une machine de 16 Go.

## PySide6 (LGPL-3.0)

Obligations respectées par l'architecture : PySide6 reste une bibliothèque **séparée** (installée dans `runtime\main`,
remplaçable), le texte de la licence et les liens vers le code source figurent dans `THIRD_PARTY_NOTICES.md`, aucune
modification de PySide6. Si un jour le logiciel est gelé en un seul exécutable, ces conditions sont à revoir.

## TripoSR

MIT (code et poids). La page du modèle demande de ne pas créer intentionnellement de modèles 3D choquants ou véhiculant des
stéréotypes : reprise dans le contrat d'utilisation. Le jeu d'entraînement s'appuie sur un sous-ensemble d'Objaverse (CC-BY).
Le code embarque des fichiers de HuggingFace sous Apache-2.0 (en-têtes conservés dans `vendor/TripoSR`, licence jointe à
l'installateur). Le lecteur d'image est DINO ViT-B/16 (Apache-2.0).

## Bibliothèques

`scripts/licences_report.py` lit la licence déclarée par chaque paquet installé et classe : *à vérifier* (non commercial, GPL,
AGPL, propriétaire), *permis avec obligations* (LGPL), *non déclarée*. La CI l'exécute sur l'installation de test et joint le
rapport à la release. Les bibliothèques CUDA (`nvidia-*`) tirées par PyTorch sont sous licence NVIDIA : elles sont
téléchargées chez l'utilisateur depuis l'index de PyTorch, le logiciel ne les redistribue pas.

## Si un jour tu vends ou partages (figurines, fichiers 3D ou logiciel)

- [ ] Lire le rapport `licences-composants.txt` de la release : aucun paquet dans « A VERIFIER » sans explication écrite.
- [ ] Faire relire `THIRD_PARTY_NOTICES.md` ; rédiger un contrat d'utilisation (il n'y en a plus : l'ancien a été retiré avec la vente).
- [ ] Remplacer tout modèle « usage personnel seulement » par un modèle permissif, ou obtenir un accord commercial.
- [ ] Confirmer la licence des poids U²-Net (ou passer à un modèle de détourage dont les poids sont explicitement permissifs).
- [ ] Avis juridique sur TripoSG (figurines passées) et sur la responsabilité liée aux images fournies (personnages, marques).
- [ ] Ne jamais ajouter un modèle ou une bibliothèque sans lire sa licence : la liste « exclus » ci-dessus s'allonge souvent.

## Idées pour plus tard (préparation d'image par IA)

Sous licence Apache-2.0 d'après leurs pages : FLUX.2 klein 4B (environ 13 Go de mémoire vidéo, 4 étapes) et Qwen-Image-Edit-2511
(versions GGUF de 10 à 13 Go, 32 Go de RAM conseillés). Non commerciaux, donc à exclure : FLUX.1 Kontext [dev], FLUX.2 klein 9B.
À vérifier à nouveau le jour où cette fonction est développée.
