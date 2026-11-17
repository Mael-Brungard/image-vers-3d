# Dépannage

Premier réflexe : menu Démarrer → **ThreeRex** → **Diagnostic**. Il liste ce qui fonctionne (OK) et ce qui manque (ECHEC).
Copie son contenu quand tu demandes de l'aide, avec le fichier `%LOCALAPPDATA%\ThreeRex\logs\studio.log`.

| Symptôme | Cause probable | Que faire |
|---|---|---|
| « Windows a protégé votre ordinateur » à l'installation | installateur non signé | « Informations complémentaires » → « Exécuter quand même » (normal : l'installateur n'est pas signé, et c'est ton propre fichier) |
| L'installation des composants échoue | pas d'Internet, disque plein, antivirus, proxy d'entreprise | vérifier la connexion et 10 Go libres ; menu Démarrer → **Réparer l'installation** ; journal : `<dossier d'installation>\logs\setup_runtime.log` |
| Diagnostic : « CUDA indisponible » | pilote NVIDIA trop ancien, ou pas de carte NVIDIA | mettre à jour le pilote, puis **Réparer l'installation** ; sans carte NVIDIA le calcul se fait sur processeur, très lent |
| « Mémoire insuffisante » pendant la génération | carte à moins de 8 Go ou autre programme gourmand | baisser la qualité (Rapide / Équilibré), fermer les jeux et navigateurs |
| TRELLIS.2 : « n'a pas pu utiliser la carte NVIDIA » | pilote NVIDIA trop ancien pour CUDA 13 (il faut la version 580 ou plus récente) | mettre à jour le pilote (nvidia.com), redémarrer ; en attendant, utiliser TripoSR |
| TRELLIS.2 : « Mémoire vidéo insuffisante, même en 512 » | un autre programme occupe la carte, ou carte trop juste | fermer jeux, navigateurs et autres générateurs 3D, puis réessayer ; en 1024 le logiciel retente déjà en 512 tout seul |
| TRELLIS.2 : la ligne d'état dit « refait en 1024 / en 512 / avec la texture standard » | mémoire vidéo insuffisante pour le réglage choisi (Ultra, texture très fine, précision Haute) | normal : le résultat est celui du réglage plus léger ; pour éviter l'attente perdue, choisis directement Détaillé et la texture standard |
| TRELLIS.2 : précision « Haute » ou « Ultra » très longue puis repli | ces réglages dépassent souvent une carte de 12 Go | repasser en Standard / Détaillé |
| TRELLIS.2 : le téléchargement s'arrête | connexion coupée, pare-feu | relancer « Installer le moteur » : il reprend où il s'était arrêté ; autoriser `github.com` et `huggingface.co` |
| TRELLIS.2 : « Le programme du moteur ne démarre pas » | DLL Windows manquante (Visual C++ Redistributable), antivirus, Windows ancien | installer les « Visual C++ Redistributable » de Microsoft, vérifier la quarantaine de l'antivirus, puis « Installer le moteur » (l'archive déjà téléchargée est réutilisée) |
| TRELLIS.2 n'apparaît pas dans la liste des moteurs | aucun pilote NVIDIA détecté | installer le pilote NVIDIA (version 580 ou plus récente), relancer le logiciel |
| TRELLIS.2 : repartir de zéro | fichiers abîmés | supprimer le dossier `%LOCALAPPDATA%\ThreeRex\engines\trellis` puis réinstaller le moteur depuis la fenêtre |
| Le logiciel ne s'ouvre pas, une boîte d'erreur apparaît | composant manquant ou abîmé | **Réparer l'installation** ; sinon envoyer `studio.log` |
| Le logiciel ne s'ouvre pas, aucun message | échec très tôt | lancer **Diagnostic** ; regarder `logs\studio_console.log` |
| Le premier calcul ne démarre pas | téléchargement des modèles bloqué (pare-feu) | autoriser l'accès à `huggingface.co` et `github.com` ; relancer |
| Le modèle est de travers dans l'autre logiciel | conventions d'axes différentes | utiliser les boutons de rotation de la visionneuse avant l'export |
| Le détourage mange une partie de la figurine | corps de la même teinte que le fond | utiliser un fond uni d'une couleur très différente (le prompt ChatGPT fourni bascule sur fond vert si la figurine est grise) |
| Chemin ou nom d'utilisateur contenant des accents | TRELLIS.2 reçoit des chemins relatifs sans accents, TripoSR est sans souci | si une erreur mentionne un chemin, réinstaller dans un dossier simple (`C:\ThreeRex`) et envoyer `studio.log` |

## Désinstaller

Paramètres Windows → Applications → ThreeRex → Désinstaller. Le programme demande s'il faut aussi supprimer les modèles
téléchargés, le cache et les journaux (`%LOCALAPPDATA%\ThreeRex`, plusieurs Go). Réponds « Non » si tu comptes réinstaller.
