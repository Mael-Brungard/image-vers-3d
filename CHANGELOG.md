# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; numérotation `MAJEUR.MINEUR.CORRECTIF`.

## [Non publié]

### Ajouté
- **Export « STL pour l'impression 3D »** : troisième format de la barre d'export (GLB / OBJ / STL), avec une petite fenêtre
  « Impression 3D » (hauteur de la figurine en mm, aplatissement du dessous). Le maillage est soudé (un `.glb` duplique les sommets
  le long des coutures de texture), nettoyé (faces dégénérées ou en double, poussières flottantes), son sens est rendu cohérent, chaque
  trou est fermé, le dessous est aplati si besoin (au plus 1,5 % de la hauteur ; rien si le bas est déjà plat, comme un socle),
  puis il est mis à l'échelle, posé sur Z = 0 et centré (Z vers le haut, comme les logiciels de tranchage). Le rapport dit la
  vérité : surface fermée ou non (et alors un avertissement sans boîte modale : toast, barre d'état, robot), taille, volume en cm³,
  trous fermés, morceaux retirés. Fonctionne avec les trois moteurs ; le « Pivoter / Redresser » fait à la main est pris en compte.
  Limites dans `docs/QUALITY.md` (épaisseur des parois et auto-intersections non vérifiées ; pas de couleurs dans un STL).
- **Moteur « Qualité maximale » (TRELLIS.2)** : modèle libre bien plus détaillé que TripoSR, avec textures PBR dans le `.glb`.
  Téléchargé à la demande (bouton « Installer le moteur », environ 7,5 Go, reprise et vérification des sommes de contrôle), calcul
  dans un programme séparé (trellis.cpp), qualités Rapide (512) / Détaillé (1024) / Maximum, repli automatique en 512 si la
  mémoire vidéo manque, détourage BiRefNet, export GLB identique ou OBJ avec texture. Voir `docs/QUALITY.md`.
  Non essayé sur une vraie carte NVIDIA : voir les limites dans ce document.
- Diagnostic : état du moteur « Qualité maximale ».
- **Meilleur résultat possible** : variantes multiples (1 à 4, sélecteur sous le modèle), qualité « Ultra » (1536, expérimental),
  texture très fine (atlas 4096 px, décodage PBR 1024, expérimental), précision des poids « Haute » (q8) téléchargeable à part,
  échelle de repli automatique si la mémoire vidéo manque (texture fine → standard, 1536 → 1024 → 512).
- **Image de départ** : conseils à l'ouverture (image petite, floue, objet coupé par le bord ; jamais bloquants), prompt ChatGPT
  copiable depuis la page Paramètres, guide `docs/IMAGE_DE_DEPART.md`.
- Moteur « Qualité maximale », robustesse : proposé seulement avec un pilote NVIDIA ; programme installé dans un dossier par
  version, vérifié au démarrage (DLL manquante, antivirus) avant le téléchargement des modèles ; poids épinglés à une révision
  précise de Hugging Face ; chemins ASCII relatifs transmis au programme (nom d'utilisateur avec accents) ; fermer la fenêtre
  arrête le calcul et libère la carte graphique ; la mémoire de TripoSR est libérée avant TRELLIS.2 ; réglages figés pendant
  un calcul ; une fois les modèles téléchargés, l'archive du programme est supprimée.

### Modifié
- **Usage personnel** : le logiciel n'est plus destiné à la vente. Pas de licence, de compte, d'essai ni de serveur ; le
  contrat d'utilisation (EULA) et le guide de vente sont retirés. (Le travail sur les licences reste dans le tag Git
  `licences-archive` et la branche `archive/licences`.)
- **Le logiciel s'appelle maintenant ThreeRex** (avant : « Image vers 3D »). Au premier lancement, les réglages et le dossier de
  données de l'ancien nom sont repris (modèles déjà téléchargés compris). Le nouvel installateur a son propre identifiant : il
  s'installe à côté de l'ancienne version, qu'on peut désinstaller une fois ThreeRex lancé une fois.
- **Nouvelle interface ThreeRex** : identité T-Rex (orange incandescent et violet électrique, formes angulaires, logo et mascotte
  vectoriels), barre du haut avec onglets « Image vers 3D » / « Mes créations » / « Paramètres », zone d'import avec halo animé et
  balayage de l'image, « Réglages avancés » repliables (moteur avec pastille « Recommandé », précision, qualité, options en puces,
  « Plus d'options »), grand visualiseur avec gestes Faire pivoter / Déplacer / Zoom / Réinitialiser et plein écran (F11),
  animation de reconstruction pendant le calcul, transition de l'image vers le modèle, particules, panneau de gauche
  redimensionnable, robot assistant (bulle d'astuce selon l'état, astuces réelles au clic), pastilles du pied de page (taille
  de l'image, moteur, durée mesurée de la dernière génération). Un seul thème, sombre : l'ancien choix clair / « Système » disparaît.
  Rien n'est inventé à l'écran (pas de « temps estimé » ni de pourcentage).
- **Effets visuels** : nouveau réglage qui coupe halos, particules, robot animé et transitions, en plus de « Réduire les animations » ;
  les effets se mettent en pause pendant un geste dans le visualiseur (une seule horloge à 30 images par seconde).
- **Mes créations** : liste des modèles enregistrés (vignette, moteur, taille, date) ; ouvrir, afficher le dossier, retirer de la
  liste (le fichier n'est jamais supprimé ; un fichier déplacé est signalé).
- Page **Paramètres** (remplace le menu flottant) : taille du texte, animations, effets, carte graphique, dossier des données,
  prompt ChatGPT, journal, licences.
- Mise en page vérifiée automatiquement (`tests/scenarios/layout_audit.py`) à 4 tailles de fenêtre et 3 tailles de texte :
  texte coupé, chevauchements, débordements, défilement horizontal, bulle tronquée.
- Les erreurs et confirmations ne passent plus par des fenêtres modales : panneau d'erreur en ligne (Réessayer, Copier les
  détails, Ouvrir le journal, Revenir au modèle) et notifications qui disparaissent seules.
- Le choix « OBJ avec texture » devient un contrôle de format ; « Aperçu du détourage » devient une bascule Originale / Détourée
  sur l'image chargée. Une nouvelle image remet le visualiseur à zéro.
- Nouvelle icône de l'application : la tête de T-Rex de la mascotte (`scripts/make_icon.py`).

### Corrigé
- Mise en page sous Windows (trouvé par la CI) : le nom du GPU était coupé dans la barre du haut sur la fenêtre la plus petite,
  et la pastille « Dernière génération » était rognée à 130 % de texte. La barre du haut affiche maintenant « GPU : RTX 4070 Ti »
  (le nom complet reste dans l'infobulle et la page Paramètres) ; les pastilles du pied de page se règlent sur la largeur réelle
  de leur colonne, mesurée après la mise en page, au lieu d'une part estimée de la fenêtre.
- Bulle du robot : une astuce qui tenait en deux lignes pouvait être coupée par « … » quand une ligne tombait à moins d'un pixel de
  la largeur disponible (la mesure du texte arrondissait, la coupe non). Constaté sur la CI Linux ; test de non-régression sur toutes
  les astuces, trois tailles de texte et mille largeurs. Les pastilles du pied de page ne forcent plus la largeur de leur colonne :
  elles n'ont plus à l'élargir au détriment de la bulle, et leur affichage ne dépend plus de l'historique (une pastille qui n'y
  tient pas est masquée, comme prévu).
- Tests : ils ne dépendent plus du réglage « Afficher les animations dans Windows » de la machine (les serveurs de CI le coupent,
  l'application passait en mouvement réduit et trois contrôles échouaient). Le comportement de l'application, lui, n'a pas changé :
  elle respecte toujours ce réglage. La lecture du réglage est maintenant testée avec un faux appel Windows.
- Plantage `QListView.update() takes exactly one argument` avec PySide6 6.9 (le rafraîchissement du thème appelait `update()`
  sans argument sur les vues) ; test de non-régression ajouté.
- Release : le rapport des licences est écrit à la racine du dépôt, et les journaux d'échec de l'installateur sont envoyables.

### Ajouté
- Accessibilité : focus visible au clavier seulement, tous les contrôles nommés, texte à 100 / 115 / 130 %, option
  « Réduire les animations » (et respect du réglage de Windows), contrastes vérifiés par des tests.
- Raccourcis : Ctrl+Entrée (générer), Ctrl+0 (recentrer), Ctrl+1/2/3 (onglets), F11 (plein écran), Échap (quitter le plein écran ou fermer une notification).
- Visualiseur : rotation automatique, affichage du maillage, pastille d'information sur le modèle.
- `docs/DESIGN.md`, `design/tokens.json`, `tests/test_theme.py`, `scripts/render_ui_screens.py`.

## [0.1.0] - à publier

Première version structurée en dépôt avec installateur Windows.

### Ajouté
- Installateur Windows (Inno Setup + uv) : installation par utilisateur, sans droits administrateur ; PyTorch et les
  bibliothèques sont téléchargés à l'installation, versions verrouillées avec sommes de contrôle.
- Raccourcis « Diagnostic » et « Réparer l'installation ».
- Publication automatique de l'installateur sur une release GitHub (tag `v*`), avec test d'installation silencieuse.
- Tests automatiques sur Linux et Windows.

### Modifié
- Code réorganisé en paquet Python `threerex` ; journaux et modèles téléchargés rangés dans
  `%LOCALAPPDATA%\ThreeRex`.
- Détourage : le modèle U²-Net est nommé explicitement (le modèle par défaut de rembg récent est non commercial).
- Export : maillage nettoyé (fragments flottants retirés), allégé à 400 000 faces, sans chemins locaux, couleurs
  correctes dans les `.glb`.
- Moteur TripoSG : **retiré de la version distribuée** (licence : code dérivé de HunyuanDiT qui exclut l'Union européenne).
  Le code reste dans le dépôt, désactivé : le moteur n'apparaît que s'il est déjà présent sur l'ordinateur.
