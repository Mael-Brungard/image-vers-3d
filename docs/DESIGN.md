# Design de l'interface

Ce document décrit le système de design de « ThreeRex » : ce qu'il y a dans l'interface, pourquoi, et comment le
modifier sans le casser. Il remplace l'ancien thème graphite et ambre. Le point de départ est une maquette générée par IA
(mascotte T-Rex, orange incandescent et violet électrique) : l'identité en est reprise et poussée plus loin, mais chaque
texte, chaque pastille et chaque réglage de l'écran correspond à une vraie fonction du logiciel.

Le code se trouve dans `src/threerex/` : `theme.py` (couleurs, feuille de style), `fx.py` (mascotte, logo, robot, halos,
animations, panneaux), `widgets.py` (composants), `viewport.py` (visualiseur 3D et ses calques), `pages.py` (« Mes
créations » et « Paramètres »), `print_dialog.py` (réglages d'impression 3D), `studio.py` (la fenêtre et son état).

## Parti pris

L'application sert à une tâche précise : transformer une image en objet 3D, le vérifier, l'enregistrer. L'identité doit se
voir et se sentir, **sans jamais ralentir la manipulation** : les effets d'ambiance (halos, particules, robot) s'arrêtent
d'eux-mêmes pendant un geste dans le visualiseur, et un réglage « Effets visuels » les coupe tous.

- **Deux couleurs, deux rôles.** L'orange incandescent (`accent`) désigne l'action : « Générer la 3D », « Enregistrer sous… »,
  la sélection, la progression. Le violet électrique (`violet`) dessine la structure : cadres, halos, bordures, aides.
  Un seul bouton plein par vue.
- **Un seul thème, sombre.** Les halos et les lueurs n'ont de sens que sur fond sombre ; il n'y a donc volontairement ni
  thème clair ni thème « Système » (l'ancien réglage est ignoré).
- **Formes angulaires.** Les panneaux, boutons et le cadre du visualiseur ont des angles coupés (comme dans la maquette) ;
  les petits contrôles (curseur, interrupteur, champs) restent arrondis pour rester lisibles à 13 px.
- **Une zone 3D immense.** Le visualiseur prend tout l'espace libre ; le panneau de gauche se redimensionne à la
  souris (poignée à points entre les deux, largeur mémorisée).
- **Les états enseignent.** Le visualiseur vide montre le T-Rex et les raccourcis ; l'assistant (le robot) commente
  l'état courant dans une bulle et donne une vraie astuce quand on clique dessus.
- **Aucune fenêtre modale pour signaler un problème.** Une erreur s'affiche dans le visualiseur avec ses actions
  (Réessayer, Copier les détails, Ouvrir le journal, Revenir au modèle) ; les confirmations sont des notifications.
  La seule fenêtre à part est un **choix**, jamais un message : « Impression 3D » (`print_dialog.py`), qui s'ouvre à
  l'enregistrement en STL pour demander la hauteur de la figurine. Un STL qu'on n'a pas pu fermer est signalé comme une erreur :
  notification orange, barre d'état et bulle du robot.
- **Honnêteté du contenu.** Rien n'est inventé : pas de pourcentage ni de « temps estimé » (le moteur ne les fournit pas),
  pastilles du pied de page = données réelles (taille de l'image, moteur choisi, durée *mesurée* de la dernière génération).
  L'animation de reconstruction pendant le calcul est un décor : elle ne représente pas l'avancement.

## Structure de la fenêtre

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ [T-Rex] ThreeRex   │ Image vers 3D │ Mes créations │ Paramètres │   ● GPU : …  │  barre du haut
├──────────────────────────┬────────────────────────────────────────────────────┤
│ Importer ton image       │                                       [⟳][▢][?][⛶] │
│  (halo, dépôt, scan)     │            Visualiseur 3D                          │
│ Réglages avancés ▾       │   vide : T-Rex · calcul : reconstruction · résultat│
│  Moteur · Précision      │                                                    │
│  Qualité                 │      [Faire pivoter][Déplacer][Zoom][Réinitialiser]│
│  Options de génération   ├────────────────────────────────────────────────────┤
│  Plus d'options ▸        │ Format [GLB|OBJ|STL]               📁 [Enregistrer]│
│ [   Générer la 3D  →  ]  │                                                    │
├──────────────────────────┴────────────────────────────────────────────────────┤
│ ◌ Image : 900×700 ◌ Moteur : TripoSR  │ progression │ (bulle d'astuce) [robot]│  pied de page
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Barre du haut** : logo, trois onglets (Ctrl+1, Ctrl+2, Ctrl+3) et pastille du calcul (vert « GPU : … » ou ambre
  « Processeur (lent) »). Sous 1160 px de large, l'accroche du logo disparaît pour laisser la place au nom de la carte ;
  la marque est retirée du nom affiché (« GPU : RTX 4070 Ti »), le nom complet reste dans l'infobulle.
- **Panneau de gauche** : « Importer ton image » (zone de dépôt avec halo animé ; à l'import, une ligne lumineuse balaie
  l'image), « Réglages avancés » repliable, bouton principal toujours visible en bas.
- **Visualiseur** : quatre pages (vide, calcul, résultat, erreur). Résultat : gestes Faire pivoter / Déplacer / Zoom /
  Réinitialiser, outils (rotation automatique, Redresser et Pivoter, maillage, aide, plein écran), pastille d'information,
  sélecteur de variante. Une transition fait se dissoudre l'image d'origine sur le modèle (900 ms ; absente si les
  effets sont coupés).
- **Pied de page** : pastilles, ligne d'état, barre de progression (pendant un calcul), bulle et robot. Les pastilles
  disparaissent l'une après l'autre quand la place manque (la place est la largeur mesurée de la colonne de gauche, pas une
  estimation : les textes n'ont pas la même largeur d'une machine à l'autre) ; le robot n'est jamais coupé.
- **Mes créations** : les fichiers réellement enregistrés (vignette = image de départ, moteur, taille, date). Retirer une
  carte **ne supprime jamais le fichier**. Un fichier déplacé est signalé « Fichier introuvable ».
- **Paramètres** : taille du texte, animations, effets visuels, carte graphique, dossier des données, prompt ChatGPT,
  journal, licences, à propos.

## Couleurs

Source unique : `design/tokens.json`, recopiée dans `theme.TOKENS` (un test échoue si les deux divergent).

| Jeton | Rôle | Valeur |
|---|---|---|
| `bg-deep` | fond le plus profond, cadre du visualiseur | `#07060F` |
| `bg-app` | fond de la fenêtre | `#0C0A18` |
| `bg-viewport` | fond du visualiseur 3D et des zones d'image | `#0A0916` |
| `bg-panel` | panneaux, cartes | `#15122B` |
| `bg-raised` | champs, boutons secondaires, info-bulles | `#1E1A3A` |
| `bg-hover` / `bg-pressed` | survol / appui | `#29234D` / `#342D5E` |
| `border` | séparateurs | `#322B63` |
| `border-strong` | contour des contrôles | `#8A80BF` |
| `text` / `text-secondary` / `text-muted` | textes | `#F4F1FF` / `#C9C2E6` / `#A9A1D0` |
| `text-disabled` | éléments désactivés (exemptés de contraste) | `#6F6898` |
| `accent` (= `accent-ui`) | orange incandescent : action principale, sélection | `#FF7A1A` |
| `accent-hover` / `accent-pressed` | survol / appui | `#FF9442` / `#E5620A` |
| `on-accent` | texte sur l'orange | `#1A0B02` |
| `accent-text` | texte orange sur fond sombre | `#FF9A4D` |
| `accent-soft` | fond d'une sélection | `#3A2113` |
| `focus` | anneau de focus clavier | `#FFB27A` |
| `violet` | violet électrique : cadres, halos | `#8B5CF6` |
| `violet-hover` / `violet-deep` | survol, trait clair / violet profond | `#A58AFF` / `#5B2DD1` |
| `violet-text` / `violet-soft` | texte violet / fond de pastille | `#B9A3FF` / `#2B2255` |
| `success` / `danger` / `warning` / `info` | états | `#4ADE9A` / `#FF8080` / `#FFD166` / `#7CC4FF` |

### Contrastes mesurés

Calculés avec la formule WCAG 2.x par `theme.contrast()` et vérifiés par `tests/test_theme.py`.

| Couple | Rapport | Seuil |
|---|---|---|
| Texte principal sur panneau | 16.4 : 1 | ≥ 7 |
| Texte secondaire sur panneau | 10.7 : 1 | ≥ 4,5 |
| Texte discret sur panneau | 7.5 : 1 | ≥ 4,5 |
| Texte discret sur visualiseur | 8.2 : 1 | ≥ 4,5 |
| Texte orange sur panneau | 8.7 : 1 | ≥ 4,5 |
| Texte du bouton principal sur l'orange | 7.4 : 1 | ≥ 7 |
| Texte violet sur panneau / sur fond de pastille | 8.5 : 1 / 6.7 : 1 | ≥ 4,5 |
| Contour des contrôles sur panneau | 5.1 : 1 | ≥ 3 |
| Orange d'interface sur panneau | 7.0 : 1 | ≥ 3 |
| Anneau de focus sur panneau | 10.3 : 1 | ≥ 3 |
| Erreur / réussite sur panneau | 7.5 : 1 / 10.6 : 1 | ≥ 4,5 |

Le violet pur (`violet`, 4.3 : 1 sur panneau) ne sert qu'à des traits et des halos décoratifs, jamais à du texte.

## Typographie

Une seule famille : **Inter** (licence OFL, fournie avec l'application, graisses 400, 500, 600). Échelle fixe
13 / 14 / 16 / 21 / 28 px ; rien en dessous de 13 px. « Taille du texte » (Paramètres) multiplie l'échelle (100, 115, 130 %) ;
tailles de contrôles, largeurs de panneaux, marges et taille minimale de la fenêtre suivent. Le nom « ThreeRex » du logo est
dessiné en italique gras, « Three » en blanc, « Rex » en dégradé orange.

## Mascotte et assistant

- **Le T-Rex** est un dessin vectoriel original (polygones, `fx.mascot_shapes`), pas une image : il s'agrandit sans perte et
  sert au logo, à l'état vide, à l'écran de calcul et à l'icône de l'application (`scripts/make_icon.py`).
- **Le robot** (`fx.Robot`) est lui aussi vectoriel : il respire, cligne des yeux, et un clic sur lui affiche l'astuce
  suivante. Les astuces sont de vrais conseils (`studio.TIPS`), et un test vérifie qu'elles tiennent dans leur bulle.
- Aucun personnage ni œuvre existante n'est reproduit : la maquette d'inspiration (dragon, mascotte) n'a servi que de direction
  artistique.

## Effets et performance

- **Une seule horloge** (`fx.Clock`, 30 images par seconde) pour tous les décors animés ; un widget ne s'y abonne que
  tant qu'il est visible. Fenêtre masquée ou inactive : aucun coût.
- **Les gestes passent avant le décor** : pendant un glisser dans le visualiseur, les particules se mettent en pause.
- **Deux interrupteurs** : « Réduire les animations » (tout est immobile, y compris les transitions) et « Effets visuels »
  (coupe halos, particules, robot animé, balayage et transition ; les réponses aux gestes restent). Windows qui désactive les
  animations est respecté.
- Les lueurs sont faites de traits translucides superposés, sans flou coûteux ; le fond est un pixmap mis en cache.

## Composants

| Composant | Fichier | États traités |
|---|---|---|
| Panneau angulaire, repliable | `fx.Panel`, `fx.CollapsiblePanel` | accent violet / orange / mixte, replié, déplié |
| Bouton lumineux | `fx.GlowButton` | principal (halo qui respire), secondaire, survol, appui, focus, désactivé |
| Puce d'option | `fx.Chip` | cochée / décochée, focus, désactivée |
| Onglets | `fx.TabBar` | actif (soulignement lumineux), survol, focus |
| Séparateur redimensionnable | `fx.GripSplitter` | repos, survol, glissement |
| Mise en page qui passe à la ligne | `fx.FlowLayout` | centrée ou non, hauteur selon la largeur |
| Bulle d'assistant | `fx.Bubble` | texte sur deux lignes au plus, `is_elided()` |
| Zone de dépôt | `widgets.DropZone` | vide (halo), fichier au-dessus, image chargée (scan, Originale / Détourée) |
| Contrôle segmenté | `widgets.Segmented` | actif animé, survol, focus, option désactivée expliquée |
| Interrupteur, curseur, listes | `widgets.Switch`, QSS | repos, survol, focus, désactivé |
| Notification / erreur | `widgets.Toast`, `widgets.ErrorPanel` | succès, avertissement, erreur ; hauteur calculée pour sa largeur |
| Pastille du calcul | `widgets.HardwareChip` | GPU (vert), processeur (ambre), nom coupé proprement |
| Visualiseur | `viewport.ViewportFrame` | vide, calcul, résultat, erreur ; calques qui se replient sur une fenêtre étroite |
| Pages | `pages.CreationsPage`, `pages.SettingsPage` | vide / remplie, fichier introuvable |

## Responsive

La fenêtre a une taille minimale de 1000 × 680 px (à 100 % du texte ; elle grandit avec l'échelle). En dessous de la taille
confortable, l'interface se replie plutôt que de couper ou de superposer :

- barre de gestes du visualiseur : icônes seules si elle ne tient pas ; sélecteur de variante au-dessus si les deux se touchent ;
- pastille d'information : les derniers éléments (« · 1024 », « · TRELLIS.2 ») disparaissent avant de couper un mot ;
- barre du haut : l'accroche du logo disparaît ; nom de la carte graphique coupé en dernier recours (info-bulle complète) ;
- pied de page : les pastilles disparaissent une à une, la bulle garde deux lignes ;
- panneau de gauche : défile verticalement, jamais horizontalement ; les puces d'options passent à la ligne ;
- pages « Mes créations » et « Paramètres » : grille de cartes qui passe à la ligne.

**Vérificateur automatique** : `python tests/scenarios/layout_audit.py` (lancé aussi par `pytest`) ouvre chaque page dans
une quinzaine d'états (vide avec chaque moteur, réglages dépliés ou repliés, image chargée, calcul, erreur, résultat, variantes,
aide, astuces du robot…), à 4 tailles de fenêtre et aux 3 tailles de texte, et signale tout texte coupé, libellé trop étroit, widget qui sort de son cadre, éléments qui se chevauchent, calque qui
passe sous un autre, défilement horizontal, bulle tronquée. Il a trouvé plusieurs défauts réels pendant la conception.

## Accessibilité

- **Clavier** : tout est atteignable à Tab ; l'anneau de focus (2 px, ≥ 3:1) n'apparaît qu'au clavier. Raccourcis :
  Ctrl+O ouvrir, Ctrl+V coller, Ctrl+S enregistrer, Ctrl+Entrée générer, Ctrl+0 recentrer, Ctrl+1/2/3 onglets, F11 plein
  écran du visualiseur, Échap quitter le plein écran ou fermer la notification. Aucun raccourci à touche simple.
- **Lecteurs d'écran** : chaque contrôle a un nom ; les boutons icône prennent leur info-bulle comme nom ; le panneau
  d'erreur reçoit le focus sur « Réessayer ».
- **Couleur** : aucune information portée par la seule couleur (texte « GPU » / « Processeur (lent) », libellés des états).
- **Mouvement** : voir « Effets et performance ».
- **Cibles** : 44 px minimum pour les contrôles.

## Modifier le design

1. Changer une couleur : éditer `design/tokens.json` **et** `theme.TOKENS` (le test `test_tokens_match_design_file` vérifie
   qu'ils restent identiques), puis relancer `pytest tests/test_theme.py` : les contrastes sont revérifiés.
2. Ajouter un composant : le placer dans `fx.py` ou `widgets.py`, lui donner tous ses états, lire ses couleurs dans
   `theme.current()` (jamais de code couleur écrit en dur), l'ajouter au tableau ci-dessus, puis relancer le vérificateur.
3. Ajouter une icône : insérer son contenu SVG Lucide dans `icons._INNER`.
4. Changer la mascotte ou l'icône : modifier `fx.mascot_shapes`, puis `python scripts/make_icon.py`.
5. Régénérer les captures de la documentation : `python scripts/render_ui_screens.py docs/images`.

## Limites connues

- Les captures et tous les contrôles automatiques sont faits en **rendu hors écran** (Linux, PySide6 6.9 et 6.12). Le
  visualiseur OpenGL ne peut pas s'y exécuter : ses couleurs, la rotation automatique, les gestes à la souris et l'animation de la
  transition n'ont pas été vus à l'écran.
- La police est vérifiée comme présente et chargeable ; le rendu des graisses 500 et 600 sous Windows n'a pas été vérifié.
  La CI Windows a toutefois déjà montré que les largeurs de texte y diffèrent de quelques pixels de celles de Linux : toute mise en page doit garder une vraie marge ou se régler sur la place mesurée.
- La barre de titre sombre sous Windows passe par une API du système (DWM) qui n'a pas pu être essayée ici ; en cas d'échec,
  la barre de titre reste celle de Windows.
- L'animation de reconstruction pendant le calcul est un décor, pas une mesure d'avancement.
- Plein écran : F11 ou le bouton du visualiseur ; non essayé sur un vrai écran avec plusieurs moniteurs.
