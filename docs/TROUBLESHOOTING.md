# Dépannage

Premier réflexe : menu Démarrer → **Image vers 3D** → **Diagnostic**. Il liste ce qui fonctionne (OK) et ce qui manque (ECHEC).
Copie son contenu quand tu demandes de l'aide, avec le fichier `%LOCALAPPDATA%\ImageVers3D\logs\studio.log`.

| Symptôme | Cause probable | Que faire |
|---|---|---|
| « Windows a protégé votre ordinateur » à l'installation | installateur non signé | « Informations complémentaires » → « Exécuter quand même » ([DISTRIBUTION.md](DISTRIBUTION.md#signature-et-smartscreen)) |
| L'installation des composants échoue | pas d'Internet, disque plein, antivirus, proxy d'entreprise | vérifier la connexion et 10 Go libres ; menu Démarrer → **Réparer l'installation** ; journal : `<dossier d'installation>\logs\setup_runtime.log` |
| Diagnostic : « CUDA indisponible » | pilote NVIDIA trop ancien, ou pas de carte NVIDIA | mettre à jour le pilote, puis **Réparer l'installation** ; sans carte NVIDIA le calcul se fait sur processeur, très lent |
| « Mémoire insuffisante » pendant la génération | carte à moins de 8 Go ou autre programme gourmand | baisser la qualité (Rapide / Équilibré), fermer les jeux et navigateurs |
| Le logiciel ne s'ouvre pas, une boîte d'erreur apparaît | composant manquant ou abîmé | **Réparer l'installation** ; sinon envoyer `studio.log` |
| Le logiciel ne s'ouvre pas, aucun message | échec très tôt | lancer **Diagnostic** ; regarder `logs\studio_console.log` |
| Le premier calcul ne démarre pas | téléchargement des modèles bloqué (pare-feu) | autoriser l'accès à `huggingface.co` et `github.com` ; relancer |
| Le modèle est de travers dans l'autre logiciel | conventions d'axes différentes | utiliser les boutons de rotation de la visionneuse avant l'export |
| Le détourage mange une partie de la figurine | corps de la même teinte que le fond | utiliser un fond uni d'une couleur très différente (le prompt ChatGPT fourni bascule sur fond vert si la figurine est grise) |
| Chemin d'installation contenant des accents | rarement problématique | si une erreur mentionne un chemin, réinstaller dans un dossier simple (`C:\ImageVers3D`) |

## Désinstaller

Paramètres Windows → Applications → Image vers 3D → Désinstaller. Le programme demande s'il faut aussi supprimer les modèles
téléchargés, le cache et les journaux (`%LOCALAPPDATA%\ImageVers3D`, plusieurs Go). Réponds « Non » si tu comptes réinstaller.
