"""
_license_keys.py - clés PUBLIQUES de vérification et adresse du serveur de licence.

Rien de secret ici : ce sont les valeurs que le logiciel livré doit connaître. La clé PRIVÉE correspondante reste sur
le serveur (jamais dans ce dépôt). Ce fichier reste VIDE dans le dépôt : `setup.py` écrit les vraies valeurs dans une
copie, au moment de la construction de la version commerciale (I3D_COMPILE_LICENSE=1, I3D_LICENSE_PUBKEYS,
I3D_LICENSE_URL, I3D_BUY_URL ; voir docs/LICENSING.md). La construction échoue tant qu'elles sont absentes ou invalides.

KEYS        identifiant de clé (« kid ») -> clé publique Ed25519 brute, en base64. Plusieurs entrées permettent de
            changer de clé de signature sans casser les licences déjà émises.
SERVER_URL  adresse de base du serveur de licence, sans « / » final (par exemple https://licence.exemple.fr).
BUY_URL     page d'achat (lien de paiement Stripe ou page de vente) ; vide = le bouton « Acheter » est masqué.
"""

KEYS: dict[str, str] = {}
SERVER_URL: str = ""
BUY_URL: str = ""
