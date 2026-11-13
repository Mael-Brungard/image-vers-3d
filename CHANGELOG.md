# Historique des versions

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; numérotation `MAJEUR.MINEUR.CORRECTIF`.

## [Non publié]

### Ajouté (licences et comptes)
- **Licence à achat unique, 2 ordinateurs**, activée une seule fois en ligne puis utilisable hors ligne ; **essai de 7 jours**
  complet. Écran Licence (saisie de la clé, essai, achat, libération de l'ordinateur), pastille « Essai : N j », entrée
  « Licence et compte » dans les réglages ; aucune fenêtre modale.
- Jetons signés Ed25519 liés à l'ordinateur (vérification en Python pur, aucune dépendance native ajoutée), clés
  `I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX` avec caractère de contrôle, détection du recul d'horloge pour l'essai.
- **Serveur de licences** (`server/`) : activation, essai, webhook Stripe (paiement, remboursement, litige), espace client par
  code envoyé par e-mail, limitation de débit, commandes d'administration, Dockerfile, Compose, Caddy (HTTPS).
- **Version commerciale** : modules de licence compilés (Cython), sources absentes de la wheel, réglages de développement sans
  effet, `verify_wheel.py`, l'installateur refuse une wheel non compilée, workflow de release mis à jour.
- Contrôles de licence répartis (démarrage, minuterie, tâches, moteur, fonctions de génération, ligne de commande), gardés par un test.
- `docs/LICENSING.md`, `docs/SERVER.md`, `tools/dev_license.py`.

### Corrigé
- Les propriétés Qt `size` des boutons n'étaient jamais appliquées (collision avec une propriété existante) : renommées
  `btnsize` ; le bouton « Générer la 3D » a maintenant bien la taille prévue (52 px).

### Modifié
- **Nouvelle interface**, conçue d'abord dans Figma puis appliquée au logiciel : thèmes sombre, clair et « Système »,
  accent ambre unique, police Inter, icônes Lucide, contrôles de 44 px, états vide / calcul / résultat / erreur dans le
  visualiseur, barre d'export, pied de page d'état, menu Réglages et aide.
- Les erreurs et confirmations ne passent plus par des fenêtres modales : panneau d'erreur en ligne (Réessayer, Copier les
  détails, Ouvrir le journal, Revenir au modèle) et notifications qui disparaissent seules.
- Le choix « OBJ avec texture » devient un contrôle de format ; « Aperçu du détourage » devient une bascule Originale / Détourée
  sur l'image chargée. Une nouvelle image remet le visualiseur à zéro.
- Nouvelle icône de l'application (graphite et ambre).

### Ajouté
- Accessibilité : focus visible au clavier seulement, tous les contrôles nommés, texte à 100 / 115 / 130 %, option
  « Réduire les animations » (et respect du réglage de Windows), contrastes vérifiés par des tests.
- Raccourcis : Ctrl+Entrée (générer), Ctrl+0 (recentrer), Échap (fermer une notification).
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
- Code réorganisé en paquet Python `imagevers3d` ; journaux et modèles téléchargés rangés dans
  `%LOCALAPPDATA%\ImageVers3D`.
- Détourage : le modèle U²-Net est nommé explicitement (le modèle par défaut de rembg récent est non commercial).
- Export : maillage nettoyé (fragments flottants retirés), allégé à 400 000 faces, sans chemins locaux, couleurs
  correctes dans les `.glb`.
- Moteur TripoSG : **retiré de la version distribuée** (licence : code dérivé de HunyuanDiT qui exclut l'Union européenne).
  Le code reste dans le dépôt, désactivé : le moteur n'apparaît que s'il est déjà présent sur l'ordinateur.
