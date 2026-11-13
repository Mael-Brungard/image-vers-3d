# Serveur de licences : installer, exploiter, sauvegarder

Le serveur (`server/licenseserver/`, FastAPI + SQLite) fait quatre choses : délivrer des **essais**, **activer** les clés,
recevoir les **paiements Stripe** (création, blocage au remboursement) et offrir un petit **espace client** (voir ses
ordinateurs, libérer une place, retrouver sa clé). Le principe général et ses limites sont dans [LICENSING.md](LICENSING.md).

> **Statut : testé sous Linux avec des e-mails et un Stripe simulés (`server/tests`, y compris le contrôle des fichiers de déploiement).**
> Jamais déployé, jamais essayé avec un vrai Stripe, un vrai serveur SMTP, ni sous charge ; pas d'audit de sécurité
> indépendant. Les fichiers Docker et Caddy n'ont pas été exécutés ici (pas de Docker dans l'environnement de travail).
> Fais le tour de la liste « Avant d'ouvrir » en bas avant de vendre.

## Ce qu'il faut

| Besoin | Détail |
|---|---|
| Un petit serveur Linux | 1 vCPU et 1 Go de mémoire suffisent largement ; Docker et Docker Compose ; ports 80 et 443 ouverts (rien d'autre) |
| Un nom de domaine | un sous-domaine (`licence.ton-domaine.fr`) dont le DNS pointe vers le serveur ; Caddy obtient et renouvelle le certificat HTTPS tout seul |
| Un compte Stripe | un produit à paiement unique et un lien de paiement (voir plus bas) |
| Un envoi d'e-mails | serveur SMTP d'un service d'envoi transactionnel (ou de ta messagerie) ; configure **SPF, DKIM et DMARC** pour ce domaine, sinon les codes de connexion et les clés finissent en courrier indésirable |

Le choix de l'hébergeur, du service d'e-mail et leurs tarifs sont les tiens : le serveur ne dépend d'aucun en particulier.

## Essayer en local (sans Docker, sans Stripe)

```
pip install -e ".[server]"
cd server
I3D_ENV=dev python -m licenseserver          # http://127.0.0.1:8000
```

(`licenseserver` vit dans le dossier `server/` : les commandes `python -m licenseserver…` se lancent depuis ce dossier, ou
dans le conteneur Docker.)

Le mode `dev` utilise une clé de signature jetable (écrite à côté de la base), un secret maître de développement et **affiche les
e-mails dans la console** (les codes de connexion s'y lisent). Il est refusé en production. Création d'une licence de test :

```
I3D_ENV=dev python -m licenseserver.admin create --email moi@exemple.fr --no-mail
```

## Installer (production)

```
git clone <ton dépôt>  &&  cd image-vers-3d
cp server/.env.example server/.env              # puis remplis server/.env (jamais commité)
docker compose -f server/docker-compose.yml up -d --build
```

Ce qui se passe : l'image du serveur est construite depuis la racine du dépôt (elle reçoit une copie de
`src/imagevers3d/_licproto.py` et `_ed25519.py`, source unique du protocole), tourne **sans droits** (utilisateur `licence`,
système de fichiers en lecture seule, aucune capacité Linux), et n'est joignable que par Caddy, qui termine HTTPS.

Le serveur **refuse de démarrer** si un secret manque ou est trop faible, ou si l'adresse publique n'est pas en `https://` :
lis le message avec `docker compose -f server/docker-compose.yml logs licences`.

### Valeurs à fournir (`server/.env`)

| Variable | Rôle |
|---|---|
| `I3D_DOMAIN`, `I3D_BASE_URL` | nom de domaine et adresse publique (`https://licence.ton-domaine.fr`) |
| `I3D_SIGNING_KEY` | clé **privée** de signature (`python tools/genkey.py`, depuis la racine du dépôt) |
| `I3D_SIGNING_KID` | identifiant de cette clé (`k1`) ; voir [le changement de clé](LICENSING.md#changer-de-clé-de-signature) |
| `I3D_MASTER_SECRET` | secret maître (32 caractères aléatoires au moins) : en dérivent les clés de licence affichées, l'empreinte de recherche, le hachage des adresses IP et des codes |
| `STRIPE_WEBHOOK_SECRET` | secret de signature du webhook (`whsec_…`) ; vide = le webhook répond 503 et refuse tout |
| `I3D_STRIPE_PAYMENT_LINK_ID` | facultatif : n'accepter que les paiements de ce lien (`plink_…`) |
| `SMTP_*`, `MAIL_FROM` | envoi des e-mails |
| `I3D_SUPPORT_EMAIL`, `I3D_PRODUCT_NAME`, `I3D_DOWNLOAD_URL`, `I3D_BUY_URL` | textes et liens affichés dans les e-mails et l'espace client |
| `I3D_MAX_DEVICES`, `I3D_TRANSFERS_PER_YEAR`, `I3D_TRIAL_PER_IP_PER_MONTH` | règles (2, 3 et 5 par défaut) |

Le fichier `.env.example` documente chaque variable ; un test (`server/tests/test_deploy_files.py`) vérifie qu'il reste d'accord avec
le code.

## Configurer Stripe

1. Crée un **produit** à paiement unique (le prix est ton choix) et un **lien de paiement** : désactive la modification de la
   quantité (une commande = une licence de 2 ordinateurs, quelle que soit la quantité), laisse la collecte de l'e-mail (Stripe la
   demande toujours). Dans le message de confirmation, écris : « Ta clé de licence t'est envoyée par e-mail dans quelques minutes. »
2. Dans *Développeurs → Webhooks*, ajoute un point d'accès `https://licence.ton-domaine.fr/stripe/webhook` pour les événements
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded` et `charge.dispute.created`.
   Copie son secret de signature dans `STRIPE_WEBHOOK_SECRET`.
3. **Teste d'abord en mode test de Stripe** (carte `4242 4242 4242 4242`) : paiement → e-mail reçu → activation → remboursement
   depuis le tableau de bord Stripe → la licence apparaît « bloquée » (`admin show`).

Comportement : le serveur vérifie lui-même la signature de chaque appel (HMAC-SHA256, fenêtre de 5 minutes, comparée à la
bibliothèque officielle dans les tests), traite chaque événement **une seule fois** (rejeu sans effet), ne crée une licence que si
le paiement est réglé, bloque la licence en cas de remboursement **total** ou de litige. Un remboursement partiel conserve la licence.
Un paiement entièrement couvert par un code promotionnel à 100 % ne produit **pas** de licence : crée-la à la main (`admin create`).

## Administration (ligne de commande)

```
docker compose -f server/docker-compose.yml exec licences python -m licenseserver.admin <commande>
```

| Commande | Effet |
|---|---|
| `create --email a@b.fr [--note "presse"] [--no-mail]` | crée une licence (cadeau, presse, paiement hors Stripe) et envoie la clé |
| `list [--email a@b.fr]` / `show <id ou clé>` | consulter : état, ordinateurs, historique |
| `revoke <id> [--reason …]` / `restore <id>` | bloquer / rétablir les **nouvelles** activations |
| `release <id> <did>` | libérer un ordinateur sans compter dans le quota annuel (cas particuliers du support) |
| `resend <id>` | renvoyer la clé par e-mail |
| `stats` | licences, activations, essais |

## Cas courants du support

| Demande | Réponse |
|---|---|
| « Je n'ai pas reçu ma clé » | regarder `list --email` ; vérifier le courrier indésirable ; `resend <id>` ; l'acheteur peut aussi la retrouver dans l'espace client (connexion par code) |
| « J'ai changé d'ordinateur » | « Libérer cet ordinateur » dans le logiciel, ou dans l'espace client ; sinon `release` |
| « Ma clé est refusée : deux ordinateurs déjà » | l'espace client montre lesquels ; en libérer un |
| « Je me suis fait rembourser mais ça marche encore » | normal (activation unique, hors ligne) : voir [Décisions](LICENSING.md#décisions-et-conséquences) |
| « Le logiciel dit que l'essai est fini » | l'essai est lié à l'ordinateur : il ne se prolonge pas ; proposer l'achat |
| Clé divulguée sur Internet | `revoke`, puis `create` une nouvelle licence pour le client légitime |

## Sauvegardes (indispensables)

Deux choses à sauvegarder, **séparément et hors du serveur** :

1. **La base** (volume Docker `donnees`, fichier `licenses.db`). Copie cohérente pendant que le serveur tourne :
   ```
   docker compose -f server/docker-compose.yml exec licences python -c "import sqlite3; s = sqlite3.connect('/data/licenses.db'); d = sqlite3.connect('/data/sauvegarde.db'); s.backup(d); d.close()"
   docker compose -f server/docker-compose.yml cp licences:/data/sauvegarde.db ./sauvegarde-$(date +%F).db
   ```
   Programme-le chaque jour (cron) et **teste une restauration** : une sauvegarde jamais restaurée n'est pas une sauvegarde.
2. **Le fichier `.env`** (au minimum `I3D_SIGNING_KEY` et `I3D_MASTER_SECRET`) dans un gestionnaire de mots de passe.
   - Sans la clé de signature : plus aucune licence ni essai ne peut être délivré ; il faudrait publier une nouvelle version du
     logiciel avec une autre clé (les anciens ordinateurs activés continuent de fonctionner).
   - Sans le secret maître : les clés déjà vendues ne sont plus retrouvées (nouvelles activations impossibles, espace client
     incapable de les réafficher).

## Mettre à jour

```
git pull
docker compose -f server/docker-compose.yml up -d --build
```

La base est créée au premier démarrage ; il n'y a **pas encore de migrations** : un changement futur du schéma devra en apporter une
(et la sauvegarder avant). Mets aussi à jour le système du serveur et les images (`docker compose pull`).

## Sécurité : ce qui est en place, ce qui ne l'est pas

En place : signature Ed25519 des jetons ; secrets uniquement dans l'environnement, refus de démarrer en production s'ils manquent ;
transactions SQLite exclusives (deux activations simultanées ne dépassent pas la limite) ; limitation de débit (clés incorrectes,
codes de connexion, essais) ; code de connexion à 8 chiffres, 10 minutes, 5 essais ; sessions stockées hachées, cookie `HttpOnly`
`Secure` `SameSite=Lax`, jeton CSRF et contrôle de l'en-tête `Origin` ; en-têtes de sécurité (CSP `default-src 'none'`, HSTS) ;
corps de requête plafonnés ; aucune documentation d'API publique ; adresses IP hachées ; réponse identique que l'adresse e-mail
existe ou non (pas de fuite de la liste des clients) ; conteneur sans droits.

**Pas en place** : audit externe ; protection contre un déni de service massif (utilise un hébergeur ou un CDN qui en offre) ;
alertes (aucune supervision : surveille `/healthz` avec un service de ton choix) ; réplication (une seule instance, SQLite) ; migrations.

## Avant d'ouvrir (liste de contrôle)

- [ ] Domaine, HTTPS valide (`https://licence.…/healthz` répond `{"ok":true}`).
- [ ] E-mail de test reçu (hors courrier indésirable) : code de connexion et clé.
- [ ] Achat complet en mode test Stripe, remboursement compris.
- [ ] Sauvegarde de la base **restaurée** une fois sur une autre machine.
- [ ] `.env` sauvegardé dans un gestionnaire de mots de passe ; la clé privée n'est nulle part dans le dépôt (`git log -p | grep -i signing`).
- [ ] Pare-feu : seuls 80 et 443 (et SSH par clé) sont ouverts.
- [ ] Version du logiciel construite avec **la clé publique correspondante** et testée de bout en bout ([LICENSING.md](LICENSING.md#construire-une-version-commerciale)).
- [ ] Mentions légales, conditions de vente, information sur les données personnelles relues par un juriste ([DISTRIBUTION.md](DISTRIBUTION.md#avant-la-première-vente)).
