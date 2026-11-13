# Design de l'interface

Ce document décrit le système de design de « Image vers 3D » : ce qu'il y a dans l'interface, pourquoi, et comment le
modifier sans le casser. La maquette Figma (fondations, composants avec tous leurs états, huit écrans dont le thème clair
et le menu Réglages) en est la référence visuelle ; le code l'applique dans `src/imagevers3d/theme.py`, `icons.py`,
`widgets.py` et `studio.py`.

## Parti pris

L'application sert à une tâche précise : transformer une image en objet 3D, le vérifier, l'enregistrer. L'interface
doit donc disparaître derrière la tâche tout en donnant une impression de précision.

- **Un seul accent, l'ambre.** Il n'apparaît que pour l'action principale, la sélection, le focus et la progression. Tout
  le reste est gris graphite légèrement froid. Pas de dégradé, pas de verre dépoli, pas d'ombre décorative.
- **Une seule action principale par vue.** Avant le résultat, « Générer la 3D » est le bouton plein ; après, c'est
  « Enregistrer sous… » (et « Générer » devient « Générer à nouveau », secondaire). Dans un écran d'erreur, c'est « Réessayer ».
- **Aucune fenêtre modale pour signaler un problème.** Une erreur s'affiche dans le visualiseur : ce qui s'est passé, quoi
  faire, et les actions (Réessayer, Copier les détails, Ouvrir le journal, Revenir au modèle). Les confirmations sont des
  notifications qui disparaissent seules.
- **Les états vides enseignent.** Le visualiseur vide montre les raccourcis (Ctrl+O, Ctrl+V, Ctrl+Entrée) au lieu de
  « Rien ici ».
- **Un seul visuel animé, discret** : un globe en fil de fer qui tourne (états vide et calcul), avec un seul trait ambre.

## Couleurs

Source unique : `design/tokens.json`, recopiée dans `theme.TOKENS` (un test échoue si les deux divergent) et dans les
variables Figma (collection « Couleurs », modes Sombre et Clair). Le thème sombre est le thème par défaut ; « Système »
suit Windows en direct.

| Jeton | Rôle | Sombre | Clair |
|---|---|---|---|
| `bg-app` | fond de la fenêtre | `#12141A` | `#F4F5F7` |
| `bg-viewport` | fond du visualiseur 3D et des zones d'image | `#0D0F13` | `#E6E9EE` |
| `bg-panel` | barres, panneau de gauche, cartes | `#1A1D23` | `#FFFFFF` |
| `bg-raised` | champs, boutons secondaires, info-bulles | `#232831` | `#F0F2F5` |
| `bg-hover` | survol | `#2B313B` | `#E6E9EE` |
| `bg-pressed` | appui, rail du curseur | `#343B47` | `#DADFE6` |
| `border` | séparateurs | `#303741` | `#D5DAE1` |
| `border-strong` | contour des contrôles (≥ 3:1) | `#7C8695` | `#6C7685` |
| `text` | texte principal (≥ 7:1) | `#ECEEF2` | `#16191F` |
| `text-secondary` | texte secondaire (≥ 4,5:1) | `#B0B8C4` | `#434C5A` |
| `text-muted` | aides et légendes (≥ 4,5:1) | `#98A1AE` | `#566170` |
| `text-disabled` | éléments désactivés (exemptés de contraste) | `#6B7482` | `#8A93A0` |
| `accent` | fond de l'action principale | `#F2A33A` | `#F2A33A` |
| `accent-hover` | action principale au survol | `#F7B55C` | `#E8940F` |
| `accent-pressed` | action principale appuyée | `#D98E26` | `#CC7F08` |
| `on-accent` | texte sur l'accent | `#1B1305` | `#1B1305` |
| `accent-text` | texte d'accent sur les fonds neutres | `#F5B351` | `#8A4F00` |
| `accent-soft` | fond d'une sélection | `#2E2616` | `#FDF0DC` |
| `accent-ui` | contour et remplissage d'accent (≥ 3:1) | `#F2A33A` | `#A85F00` |
| `focus` | anneau de focus clavier | `#F7B55C` | `#A85F00` |
| `success` | réussite, GPU détecté | `#5BCB8E` | `#17703F` |
| `danger` | erreur | `#F47C74` | `#B3261E` |
| `warning` | avertissement, calcul sur processeur | `#E7C84A` | `#7A5F00` |
| `info` | information | `#73B8F0` | `#1B62A8` |

### Contrastes mesurés

Calculés avec la formule WCAG 2.x par `theme.contrast()` et vérifiés par `tests/test_theme.py` sur chaque surface.

| Couple | Sombre | Clair | Seuil |
|---|---|---|---|
| Texte principal sur panneau | 14.5 : 1 | 17.6 : 1 | ≥ 7 |
| Texte secondaire sur panneau | 8.4 : 1 | 8.7 : 1 | ≥ 4,5 |
| Texte discret sur panneau | 6.5 : 1 | 6.3 : 1 | ≥ 4,5 |
| Texte discret sur visualiseur | 7.3 : 1 | 5.2 : 1 | ≥ 4,5 |
| Texte d'accent sur panneau | 9.2 : 1 | 6.6 : 1 | ≥ 4,5 |
| Texte du bouton principal | 8.8 : 1 | 8.8 : 1 | ≥ 7 |
| Contour des contrôles sur panneau | 4.6 : 1 | 4.6 : 1 | ≥ 3 |
| Accent d'interface sur panneau | 8.1 : 1 | 4.9 : 1 | ≥ 3 |
| Anneau de focus sur panneau | 9.4 : 1 | 4.9 : 1 | ≥ 3 |
| Erreur sur panneau | 6.4 : 1 | 6.5 : 1 | ≥ 4,5 |
| Réussite sur panneau | 8.3 : 1 | 6.1 : 1 | ≥ 4,5 |

## Typographie

Une seule famille : **Inter** (licence OFL, fournie avec l'application, trois graisses : 400, 500, 600). Échelle fixe
13 / 14 / 16 / 21 / 28 px ; rien en dessous de 13 px, chiffres de largeur fixe pour les compteurs. L'option « Taille du
texte » du menu Réglages multiplie l'échelle (100, 115, 130 %) ; tailles de contrôles, largeurs de panneaux et marges suivent.

## Espacements, formes, tailles

- Espacements : 4, 8, 12, 16, 24, 32, 48 px.
- Rayons : 8 px (contrôles), 12 px (panneaux, notifications), pastilles pour les puces.
- Contrôles de 44 px de haut, bouton principal de 52 px, icônes de 20 px (trait 1,75, Lucide).
- Le visualiseur 3D occupe toute la zone centrale, sans coins arrondis : un rendu OpenGL ne se découpe pas proprement ;
  les commandes flottantes (pastille d'information, barre d'outils, aide) sont posées par-dessus.

## Composants

| Composant | Fichier | États traités |
|---|---|---|
| Bouton (principal, secondaire, discret) | `widgets.make_button` + QSS | repos, survol, appui, focus clavier, désactivé |
| Bouton icône | `widgets.IconButton` | idem + coché (maillage, rotation auto) ; info-bulle = nom accessible |
| Interrupteur | `widgets.Switch` | éteint/allumé animé, survol, focus, désactivé |
| Contrôle segmenté | `widgets.Segmented` | actif animé, survol, appui, focus (flèches, Début, Fin), option désactivée avec explication |
| Curseur | QSS `QSlider` | repos, survol, focus, désactivé |
| Zone de dépôt | `widgets.DropZone` | vide, fichier au-dessus (glisser), image chargée avec bascule Originale / Détourée |
| Notification | `widgets.Toast` | succès, avertissement, erreur ; pause au survol ; Échap pour fermer |
| Panneau d'erreur | `widgets.ErrorPanel` | avec ou sans retour au modèle précédent |
| Barre de progression | `widgets.IndeterminateBar` | active, statique si le mouvement est réduit |
| Menu Réglages et aide | `widgets.SettingsPopover` | thème, taille du texte, animations, journal, licences |
| États du visualiseur | `studio.ViewportFrame` | vide, calcul, résultat, erreur |

## Accessibilité

- **Clavier** : tout est atteignable à Tab ; l'anneau de focus (2 px, ≥ 3:1) n'apparaît qu'au clavier, jamais après un
  clic. Raccourcis : Ctrl+O ouvrir, Ctrl+V coller, Ctrl+S enregistrer, Ctrl+Entrée générer, Ctrl+0 recentrer, Échap fermer
  la notification. Aucun raccourci à touche simple (ils gênent la saisie et la dictée vocale).
- **Lecteurs d'écran** : chaque contrôle a un nom ; les boutons icône prennent leur info-bulle comme nom ; le panneau
  d'erreur reçoit le focus sur « Réessayer ».
- **Couleur** : aucune information portée par la seule couleur (texte « GPU » / « Processeur (lent) », position de
  l'interrupteur, libellés des états).
- **Mouvement** : toutes les animations (100 à 250 ms, courbe `cubic-bezier(0.23, 1, 0.32, 1)`) passent par `theme.Motion`.
  Elles s'arrêtent si Windows désactive les animations ou si « Réduire les animations » est coché.
- **Cibles** : 44 px minimum.
- **Texte** : 130 % sans recouvrement (testé en rendu hors écran à 1000 px de large, taille minimale de la fenêtre).

## Modifier le design

1. Changer une couleur : éditer `design/tokens.json` **et** `theme.TOKENS` (le test `test_tokens_match_design_file`
   vérifie qu'ils restent identiques), mettre à jour la variable Figma, relancer `pytest tests/test_theme.py` : les
   contrastes sont revérifiés.
2. Ajouter un composant : le placer dans `widgets.py`, lui donner tous ses états, lire ses couleurs dans
   `theme.current()` (jamais de code couleur écrit en dur), le décrire dans le tableau ci-dessus.
3. Ajouter une icône : insérer son contenu SVG Lucide dans `icons._INNER` ; le test des icônes vérifie qu'elle se dessine.
4. Vérifier visuellement : `python tests/scenarios/studio_ui.py` enregistre des captures (vide, dépôt, calcul, résultat,
   erreur, clair, texte à 130 %, menu) dans le dossier donné par `IMAGEVERS3D_TEST_OUT`.

## Limites connues

- Le visualiseur OpenGL ne peut pas être exécuté en rendu hors écran : ses couleurs de thème, la rotation automatique et
  le fond sont écrits avec prudence (un échec de style n'empêche jamais l'affichage) mais n'ont pas été vus à l'écran.
- La police est vérifiée comme présente et chargeable ; le rendu des graisses 500 et 600 dépend de la pile de polices de
  Windows et n'a pas été vérifié sur Windows.
- Le menu Réglages utilise une fenêtre flottante (Qt.Popup) : son comportement au clavier sous Windows est à confirmer.
