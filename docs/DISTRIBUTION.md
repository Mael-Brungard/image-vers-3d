# Vendre et livrer le logiciel

Ce document rassemble ce qu'il faut décider avant de vendre ; le système de licence est écrit mais pas encore déployé, les autres choix ne sont pas faits.
Les informations sur les services (prix, conditions) datent de novembre 2026 et changent : vérifie-les sur les sites officiels.

## Comment un client reçoit l'installateur

Les releases d'un dépôt GitHub **privé** ne sont téléchargeables que par les personnes qui ont accès au dépôt : tes clients
ne peuvent pas les utiliser. Il faut donc un canal de livraison.

| Option | Principe | À considérer |
|---|---|---|
| Plateforme de vente de produits numériques (Gumroad, Lemon Squeezy, itch.io, Paddle…) | tu y téléverses l'installateur ; elle encaisse, livre le fichier et gère les reçus | souvent la plus simple pour démarrer ; commission ; certaines gèrent la TVA européenne (« marchand de référence ») et proposent des clés de licence : à vérifier |
| Site à toi + paiement (Stripe…) + stockage de fichiers | tu contrôles tout | plus de travail (TVA, factures, remboursements, support du téléchargement) |
| Dépôt GitHub public « releases seulement » | la CI y dépose l'installateur | téléchargement libre pour tout le monde : pas de vente contrôlée |

La CI actuelle dépose l'installateur dans une release en brouillon du dépôt privé ; la mise en ligne chez le client est une
étape manuelle (téléverser le `.exe` sur la plateforme choisie), automatisable plus tard.

## Licence : essai, clé, deux ordinateurs

Le logiciel exige une **licence** : essai de 7 jours, puis clé à achat unique valable sur 2 ordinateurs, activée une seule fois
en ligne. L'installateur peut donc être **diffusé librement** (page de vente, lien public) : sans clé, il ne sert qu'à l'essai.
Le paiement passe par **ton serveur de licences et Stripe** ([SERVER.md](SERVER.md)), pas par une plateforme de vente de fichiers :
la clé est créée et envoyée automatiquement après le paiement. Si tu préfères une plateforme (Gumroad, Lemon Squeezy…), le
serveur actuel ne la gère pas : seule la création manuelle (`admin create`) est possible.

Ce que cela protège, ce que cela ne protège pas, et comment construire la version vendable : [LICENSING.md](LICENSING.md).
Le contrat d'utilisation (`packaging/windows/EULA.fr.txt`) interdit la redistribution et le partage des clés.

## Signature et SmartScreen

Un installateur non signé déclenche l'écran bleu « Windows a protégé votre ordinateur » : l'utilisateur doit cliquer
« Informations complémentaires » puis « Exécuter quand même ». Cela fait fuir une partie des acheteurs.

- **Même signé, l'avertissement peut apparaître** tant que la réputation de l'éditeur et du fichier n'est pas établie
  (quelques semaines et des centaines d'installations). Un certificat EV n'en dispense plus automatiquement.
- **Azure Artifact Signing** (ex-Trusted Signing) : environ 10 $/mois ; réservé aux organisations aux États-Unis, au Canada, dans
  l'Union européenne et au Royaume-Uni ; les particuliers seulement aux États-Unis et au Canada. Vérifie l'éligibilité d'une
  micro-entreprise française.
- **Certificat OV classique** : environ 150 à 300 $/an ; la clé doit être sur un jeton matériel ou un service HSM, ce qui
  complique la signature depuis la CI.
- **Microsoft Store** (paquet MSIX) : Microsoft signe le paquet, sans avertissement SmartScreen ; demande un compte
  développeur et un autre format de paquet.

Mesure d'accompagnement à coût nul : publier les sommes SHA-256 (`SHA256SUMS.txt`) et expliquer dans la page de vente le
passage par SmartScreen. Pour réduire les faux positifs d'antivirus, l'installateur n'embarque pas d'exécutable « gelé » : il
installe Python et les bibliothèques officielles.

## Mises à jour

Pas de mise à jour automatique. Chaque version est un nouvel installateur à lancer par-dessus la précédente (même `AppId`,
même dossier) : le logiciel est remplacé, les modèles et les journaux (`%LOCALAPPDATA%\ImageVers3D`) sont conservés. Un
système de notification de nouvelle version est une évolution possible.

## Ce que le client fabrique

Les modèles 3D produits par TripoSR n'ont pas de restriction de licence liée au moteur (MIT). Les droits sur **l'image de
départ** sont ceux de qui la fournit : personnage de jeu, marque, œuvre d'un tiers… Le contrat d'utilisation en renvoie la
responsabilité au client ; vérifie-le avec un juriste, et dis-le clairement sur la page de vente. Pour tes propres figurines, la
même règle s'applique à toi.

## Avant la première vente

- [ ] Contrat d'utilisation relu par un juriste ; mentions légales et conditions générales de vente.
- [ ] Statut d'entreprise, TVA et facturation (ou plateforme qui s'en charge), droit de rétractation sur un produit numérique.
- [ ] Canal de livraison choisi, page de vente avec configuration requise et mention SmartScreen.
- [ ] Serveur de licences en ligne, Stripe configuré, **parcours d'achat testé de bout en bout** ([SERVER.md](SERVER.md#avant-douvrir-liste-de-contrôle)).
- [ ] Mentions sur les données personnelles (e-mail, identifiant d'ordinateur haché, adresse IP hachée) dans le contrat et la page de vente.
- [ ] [Liste de contrôle des licences](LICENSES.md#avant-de-vendre).
- [ ] Validation sur au moins deux ordinateurs réels ([BUILD_AND_RELEASE.md](BUILD_AND_RELEASE.md#validation-sur-un-vrai-ordinateur)).
- [ ] Une adresse de support et une procédure : « copie-moi le contenu de Diagnostic et le fichier `studio.log` ».
