# Licences et comptes : fonctionnement, limites, construction d'une version

Ce document décrit le système qui réserve le logiciel à ceux qui l'ont acheté : ce que vit l'acheteur, comment c'est
construit, **ce que cela empêche et ce que cela n'empêche pas**, et comment fabriquer une version vendable. Le serveur est
décrit dans [SERVER.md](SERVER.md).

> **Statut : écrit et testé sous Linux (protocole, serveur, interface hors écran, compilation Cython), jamais exécuté sur
> Windows ni contre un vrai Stripe, un vrai serveur de courriel ou un vrai hébergement.** La liste de ce qui reste à valider
> est en fin de document.

## Principe en une page

- **Essai** : au premier lancement, la personne peut démarrer **7 jours d'essai complet**. Le serveur signe un jeton d'essai
  lié à son ordinateur ; il n'y a pas de compte à créer.
- **Achat unique** (paiement Stripe) : le serveur crée une licence, l'associe à l'adresse e-mail de l'acheteur et lui envoie
  une **clé** `I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX`.
- **Activation une seule fois** : l'acheteur colle sa clé dans le logiciel ; l'ordinateur contacte le serveur, qui renvoie un
  jeton signé **lié à cet ordinateur**. Ensuite le logiciel fonctionne **entièrement hors ligne**, sans limite de durée.
- **Deux ordinateurs** par licence. Pour en changer : « Libérer cet ordinateur » dans le logiciel, ou depuis l'espace client
  (connexion par code envoyé par e-mail, sans mot de passe). 3 libérations par an et par licence ; au-delà, le support (`release`).
- **Remboursement ou litige bancaire** : la licence est bloquée (plus aucune nouvelle activation). Les ordinateurs déjà
  activés **continuent de fonctionner** : c'est un choix du propriétaire (pas d'appel au serveur après l'activation), voir
  [Décisions et conséquences](#décisions-et-conséquences).
- Le code qui décide « licence valable ou non » est **compilé** (Cython) dans la version vendue ; la signature du jeton est
  vérifiée par une clé publique embarquée, la clé privée ne quitte jamais le serveur.

## Ce que cela empêche, et ce que cela n'empêche pas

**Aucune protection côté client d'un logiciel Python n'est incassable** : le programme tourne sur l'ordinateur de celui qui
voudrait le copier, qui contrôle sa mémoire, ses fichiers et ses bibliothèques. Le but réaliste est de rendre le contournement
**plus coûteux et plus rare que l'achat**, et de rendre la copie triviale (envoyer l'installateur à un ami) inutile.

| Attaque | Résultat |
|---|---|
| Copier l'installateur ou le dossier installé sur un autre ordinateur | **Bloqué** : le jeton est lié à l'identifiant de l'ordinateur (`did`), et ne vaut rien ailleurs |
| Partager une clé de licence sur Internet | **Limité** : 2 ordinateurs au plus ; au-delà, l'activation est refusée tant qu'une place n'est pas libérée par le titulaire |
| Fabriquer une clé ou un jeton | **Bloqué** : clé de 120 bits dérivée d'un secret serveur ; jeton signé Ed25519, clé privée absente du logiciel |
| Modifier le fichier `license.json` (dates, état) | **Bloqué** : toute modification casse la signature |
| Reculer l'horloge pour prolonger l'essai | **Détecté** (le logiciel mémorise le plus récent instant vu, protégé par un code d'authentification ; 24 h de tolérance) |
| Remplacer la clé publique embarquée par la sienne | **Freiné** : elle est dans un binaire compilé, pas dans un fichier texte ; mais voir ci-dessous |
| Lire le code de la vérification | **Freiné** : modules de licence compilés, sans sources ni textes d'aide dans la wheel |
| Variables d'environnement « développeur » | **Sans effet** dans la version vendue (testé : `is_compiled()` les ignore) |
| Remplacer le module de licence par un faux ; modifier le binaire ; débogueur ; rejouer l'activation d'un autre | **Non empêché** : voir plus bas |
| Supprimer l'état de l'essai pour en recommencer un | **Limité** : l'essai est lié à l'identifiant de l'ordinateur côté **serveur** (redemander renvoie le même jeton, qui expire), plafonné par adresse IP (5 par mois) ; un nouvel identifiant d'ordinateur (réinstallation de Windows) donne un nouvel essai |

**Ce qui reste possible pour quelqu'un de déterminé et compétent** : le logiciel est en grande partie du Python lisible
(interface, génération, export). Un attaquant peut remplacer le module compilé par un module qui répond toujours « licence
valide », ou corriger le binaire. Les contrôles sont répartis dans le code (voir le tableau ci-dessous) pour que
l'opération demande du travail à chaque version, mais **rien ne l'empêche absolument**. Ces versions piratées existent pour
presque tous les logiciels vendus ; l'effort raisonnable est de les rendre pénibles à maintenir (chaque mise à jour déplace
les points de contrôle) et de proposer une raison d'acheter (mises à jour, support, installation propre).

Les pistes supplémentaires, avec leur coût, sont en fin de document ([Durcissements possibles](#durcissements-possibles)).

## Parcours de l'acheteur

1. Il télécharge l'installateur (page de vente) et l'installe : [DISTRIBUTION.md](DISTRIBUTION.md).
2. Au premier lancement, l'écran **Licence** propose : saisir une clé, démarrer l'essai de 7 jours, acheter, ouvrir l'espace client.
3. Pendant l'essai, une pastille « Essai : N j » est visible en haut ; à la fin, le logiciel redirige vers l'écran Licence
   (les fichiers déjà exportés restent à la personne ; aucun contenu n'est supprimé ni verrouillé).
4. Avec une licence : plus de pastille ; « Licence et compte » dans les réglages montre l'état et permet de libérer l'ordinateur.
5. Si le jeton ne correspond plus à l'ordinateur (réinstallation de Windows, changement de carte mère, copie de dossier), le
   logiciel le dit clairement et propose de réactiver (ce qui consomme une place : libérer l'ancienne depuis l'espace client).

Les textes sont écrits en français (tutoiement), sans fenêtre modale ; l'écran est accessible au clavier et à 130 % de texte
(captures : `python scripts/render_ui_screens.py docs/images`).

## Le protocole

Source unique : [`src/imagevers3d/_licproto.py`](../src/imagevers3d/_licproto.py) (le serveur en reçoit une copie à la
construction de l'image). Bibliothèque standard seulement ; la vérification Ed25519 est écrite en Python pur
([`_ed25519.py`](../src/imagevers3d/_ed25519.py), RFC 8032, refuse les signatures non canoniques) pour **n'ajouter aucune
dépendance native au logiciel**. Le paquet `cryptography` n'est utilisé que côté serveur, dans les tests et par les outils de développement.

**Jeton** : `I3D1.<charge utile en base64url>.<signature en base64url>`. La charge utile est du JSON canonique (clés triées,
sans espaces) :

| Champ | Sens |
|---|---|
| `v` | version du format (1) |
| `kid` | identifiant de la clé de signature (permet de changer de clé) |
| `typ` | `license` ou `trial` |
| `lid` | identifiant de la licence (`trial` pour un essai) |
| `did` | identifiant de l'ordinateur (voir ci-dessous) |
| `iat`, `exp` | émission et expiration (Unix) ; `exp` vaut `null` pour une licence, jamais pour un essai |
| `plan`, `dev` | formule (`personal`) et nombre d'ordinateurs autorisés |

La signature porte sur `b"I3D-LICENSE-v1\0" + charge_utile` : le préfixe interdit de réutiliser une signature d'un autre usage.

**Identifiant d'ordinateur (`did`)** : SHA-256 de `"I3D-DEVICE-v1|" + identifiant de la machine`, tronqué à 32 caractères
hexadécimaux. L'identifiant brut (GUID de la machine Windows : `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` ; sous Linux
`/etc/machine-id`) n'est **jamais transmis** ; à défaut, un identifiant aléatoire est conservé dans `device.id`.

**Clé de licence** : `I3D-` + 25 caractères (alphabet de Crockford, sans I, L, O, U) = 24 caractères tirés d'un HMAC du
secret maître et de l'identifiant de licence (120 bits) + 1 caractère de contrôle. La saisie tolère minuscules, espaces,
absence du préfixe et confusions O/0, I/L/1. Le serveur ne stocke **pas** la clé : il en garde une empreinte de recherche
(HMAC avec un autre secret dérivé) et sait la **recalculer** pour la réafficher dans l'espace client. Une fuite de la base seule
ne donne donc aucune clé.

**Échanges avec le serveur** (HTTPS, JSON) :

| Appel | Données envoyées | Réponse |
|---|---|---|
| `POST /v1/activate` | clé, `did`, nom de l'ordinateur (`platform.node()`, 40 caractères), version du logiciel | jeton de licence |
| `POST /v1/trial` | `did`, version | jeton d'essai (le même à chaque appel pour un même ordinateur) |
| `POST /v1/deactivate` | le jeton de licence de l'ordinateur à libérer | confirmation |

Aucun contenu d'image ni de modèle ne transite. Aucun appel n'est fait après l'activation, sauf si la personne libère
l'ordinateur.

## Où le logiciel vérifie la licence

Une seule vérification serait facile à neutraliser ; elles sont donc dispersées. `licensing.require()` lève `LicenseError`
si l'état n'est ni « licence » ni « essai en cours » :

| Lieu | Moment |
|---|---|
| `studio.MainWindow` | au démarrage (affiche l'écran Licence au lieu de l'étude) |
| `studio.MainWindow` | toutes les 60 secondes (`QTimer`), et avant chaque tâche (`run_task`) |
| `studio.Engine` | début de `preprocess`, `generate`, `export` (et variantes) |
| `image_to_3d` | `load_model`, `preprocess`, `cutout`, `generate_mesh`, `export_mesh`, `convert_image` |
| `image_to_3d.main` (ligne de commande) | avant tout traitement |

`tests/test_license_checkpoints.py` lit le code source et échoue si l'un de ces contrôles disparaît ou est déplacé ;
`tests/test_licensing_client.py` et `tests/test_license_ui.py` vérifient le comportement (états, écran Licence, tâche refusée sans licence).

## Version commerciale : la compilation

`setup.py` compile quatre modules avec Cython quand `I3D_COMPILE_LICENSE=1` :

| Module | Rôle |
|---|---|
| `_ed25519` | vérification de signature |
| `_licproto` | format du jeton, clés de licence |
| `_license_keys` | **clés publiques et adresse du serveur**, écrites au moment de la construction |
| `license` | état, activation, essai, horloge |

La construction se fait sur une copie (`build/license_c/`) : **le dépôt n'est jamais modifié**, `_license_keys.py` y reste vide.
Les sources `.py` de ces quatre modules ne sont **pas** dans la wheel ; les textes d'aide (docstrings) ne sont pas embarqués ;
la construction **échoue** si la clé publique n'est pas valide ou si l'adresse du serveur n'est pas en `https://`.

`packaging/verify_wheel.py` contrôle le résultat (binaires présents, sources absentes, clé et adresse valides, réglages
de développement sans effet) et `packaging/build_stage.py` **refuse** de préparer l'installateur avec une wheel non compilée.
`tests/test_licensing_build.py` rejoue la compilation réelle, vérifie une vraie signature avec le module compilé et refuse un
jeton de développement.

Les réglages de développement `IMAGEVERS3D_DEV_LICENSE_PUBKEY` et `IMAGEVERS3D_LICENSE_URL` ne sont lus **que par une version non
compilée** : sur une version vendue, ils sont ignorés (sinon, il suffirait de définir une variable pour se délivrer une licence).

## Construire une version commerciale

À faire **une fois** :

1. **Générer la clé de signature** (sur ta machine, hors dépôt) :
   ```
   python -m pip install cryptography
   python tools/genkey.py
   ```
   Le script affiche une clé **privée** et une clé **publique**, plus la valeur exacte de la variable `I3D_LICENSE_PUBKEYS`. Range la privée dans un gestionnaire de mots de passe (sans elle,
   plus aucune licence ne peut être émise) ; **ne la commite jamais**, ne l'envoie jamais à personne.
2. **Déployer le serveur** avec la clé privée (`I3D_SIGNING_KEY`) : [SERVER.md](SERVER.md).
3. **Renseigner les variables du dépôt GitHub** (Settings → Secrets and variables → Actions → onglet *Variables*, ce ne sont
   pas des secrets : clé publique et adresses) :

   | Variable | Valeur |
   |---|---|
   | `I3D_LICENSE_PUBKEYS` | `k1=<clé publique base64>` (plusieurs clés : `k1=...,k2=...`) |
   | `I3D_LICENSE_URL` | `https://licence.ton-domaine.fr` (adresse du serveur) |
   | `I3D_BUY_URL` | page d'achat (lien de paiement Stripe), facultatif : sans elle, le bouton « Acheter » est masqué |

Puis, à chaque version : tag `v…` comme d'habitude ([BUILD_AND_RELEASE.md](BUILD_AND_RELEASE.md)). Le workflow s'arrête avec un message
clair si les variables manquent, compile les modules, contrôle la wheel, puis construit et teste l'installateur.

**Avant la première vente, teste la chaîne complète** (rien de tout cela n'a été fait ici) : installer la version publiée sur
un ordinateur propre, démarrer l'essai, faire un vrai achat en mode test Stripe, recevoir l'e-mail, activer, couper Internet,
relancer, libérer, réactiver, tester un remboursement.

## Changer de clé de signature

Le champ `kid` permet une transition sans casser les licences déjà vendues : générer une seconde paire (`python tools/genkey.py`), publier une
nouvelle version dont `I3D_LICENSE_PUBKEYS` contient **les deux** clés (`k1=...,k2=...`), puis passer le serveur sur la nouvelle
(`I3D_SIGNING_KEY` et `I3D_SIGNING_KID=k2`). Les jetons `k1` déjà émis restent valables tant que les versions du logiciel
connaissent `k1`. Ne retire jamais une clé publique encore utilisée par des clients.

## Travailler sur le logiciel sans serveur

`tools/dev_license.py` fabrique une paire de clés jetable et une licence de développement pour **cet** ordinateur ; les tests,
les scénarios, `scripts/render_ui_screens.py` et l'intégration continue l'utilisent (`tests/conftest.py`). Il faut
`cryptography` (extra `dev`). Cette licence n'est reconnue que par une version **non compilée**.

```
python tools/dev_license.py --data-dir ./donnees-dev            # affiche les deux variables à définir
python tools/dev_license.py --data-dir ./donnees-dev --trial-days 3
```

## Données personnelles

| Donnée | Où | Pourquoi | Durée |
|---|---|---|---|
| Adresse e-mail de l'acheteur | serveur (Stripe la fournit) | envoyer la clé, connexion à l'espace client | tant que la licence existe |
| Clé de licence | **non stockée** (empreinte de recherche seulement) | retrouver la licence | — |
| Identifiant d'ordinateur haché, nom de l'ordinateur, version du logiciel, dates | serveur | limiter à 2 ordinateurs, afficher « Mes ordinateurs » | tant que la licence existe |
| Adresse IP | serveur, **hachée** avec un secret (jamais en clair) | limiter les abus (essais, clés incorrectes, codes de connexion) | compteurs purgés au bout de 7 jours ; l'empreinte reste dans la table des essais et le journal d'audit |
| Journal d'audit (activations, libérations, essais) | serveur | support, litiges | à définir par le propriétaire |

Le contrat d'utilisation (`packaging/windows/EULA.fr.txt`) le dit à l'utilisateur ; **il doit être relu par un juriste**
(information RGPD, base légale, durée de conservation, droit de suppression, mentions légales). Le logiciel n'envoie jamais
d'image, de modèle ni de chemin de fichier.

## Décisions et conséquences

Choisies par le propriétaire, avec leurs conséquences :

| Décision | Conséquence |
|---|---|
| Serveur à soi | pas de commission de plateforme, mais **le serveur doit rester en ligne** pour activer, délivrer des essais et envoyer les clés ; sauvegardes et secrets sont à ta charge ([SERVER.md](SERVER.md)) |
| Activation une seule fois, puis hors ligne | confort maximal (pas de coupure, fonctionne dans un atelier sans Internet) ; **aucune révocation après coup** : un remboursement ou une clé divulguée ne désactive pas les ordinateurs déjà activés |
| Achat unique, 2 ordinateurs | pas d'abonnement ; les mises à jour futures restent à décider (gratuites, ou payantes par version majeure) |
| Essai de 7 jours complet | essai contournable en réinstallant Windows (nouvel identifiant) ; plafonné par adresse IP |
| Pas de mot de passe | espace client par code à 8 chiffres reçu par e-mail ; pas de mots de passe à stocker ni à protéger |

Si la clé de licence d'un client est publiée (« leak »), l'unique recours est le blocage des **nouvelles** activations
(commande `revoke` de l'administration, voir [SERVER.md](SERVER.md#administration-ligne-de-commande)) et l'émission d'une nouvelle licence pour le client légitime.

## Durcissements possibles

Chacun a un coût de complexité, de support ou de confort :

| Piste | Gain | Inconvénient |
|---|---|---|
| Vérification périodique en ligne (par exemple tous les 30 jours) avec révocation | désactive les licences remboursées ou divulguées | casse le fonctionnement hors ligne promis ; support des pannes |
| Compiler davantage de code (génération, export) | plus de travail pour un attaquant | build plus lent, plus de plateformes à tester, erreurs plus difficiles à lire |
| Chiffrer les poids ou le code avec une clé dérivée de la licence | une copie sans licence ne démarre pas | la clé finit en mémoire ; complexité |
| Obfuscation commerciale / empaquetage (PyArmor, Nuitka, Themida…) | frein supplémentaire | coût de licence, faux positifs d'antivirus, aucune garantie ; à évaluer sur de vrais exemples |
| Signature de l'installateur | confiance, moins de faux positifs | [DISTRIBUTION.md](DISTRIBUTION.md#signature-et-smartscreen) |
| Filigrane discret dans les exports de l'essai | pousse à l'achat | à décider côté produit |

## Ce qui n'a pas été vérifié

- Windows : lecture de `MachineGuid`, compilation Cython avec Visual Studio (le workflow Windows la fait, jamais exécuté),
  `.pyd`, installateur, activation depuis le logiciel installé.
- Un vrai Stripe (lien de paiement, webhook signé, remboursement, litige), un vrai serveur SMTP, un vrai hébergement HTTPS.
- L'écran Licence sur un vrai affichage Windows (rendu hors écran seulement).
- Un audit de sécurité indépendant du serveur et de l'application : à faire avant des ventes importantes.
