# Construire et publier une version

## Publier (le chemin normal)

0. **Une fois** : variables du dépôt `I3D_LICENSE_PUBKEYS`, `I3D_LICENSE_URL` (et `I3D_BUY_URL`), serveur de licences en ligne :
   [LICENSING.md](LICENSING.md#construire-une-version-commerciale). Le workflow s'arrête sinon.
1. Mets à jour `version` dans `pyproject.toml` et ajoute la section correspondante dans `CHANGELOG.md`.
2. Fusionne sur `main` (le workflow **CI** doit être vert).
3. Crée et pousse le tag :
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Le workflow **Release** (`.github/workflows/release.yml`) tourne sur un serveur Windows :
   1. vérifie que le tag correspond à la version de `pyproject.toml` ;
   2. construit le logiciel (wheel **avec modules de licence compilés**), contrôle la wheel (`packaging/verify_wheel.py`),
      puis prépare le dossier de l'installateur (`packaging/build_stage.py` : uv vérifié par SHA-256, TripoSR au commit
      épinglé ; refuse une wheel non compilée) ;
   3. compile l'installateur avec Inno Setup ;
   4. **l'installe en silencieux** avec PyTorch sur processeur (`/TORCH=cpu`), exécute le diagnostic, importe l'interface,
      contrôle les raccourcis ;
   5. produit le rapport des licences des composants installés ;
   6. **le désinstalle** et contrôle que `runtime\` a disparu ;
   7. calcule les sommes SHA-256 ;
   8. dépose `ImageVers3D-Setup-x.y.z.exe`, `SHA256SUMS.txt` et `licences-composants.txt` dans une **release en brouillon**.
5. Ouvre la release en brouillon sur GitHub, lis le rapport de licences, **teste l'installateur sur un vrai ordinateur**
   (liste ci-dessous), puis publie.

Pour essayer sans tag : onglet *Actions* → *Release* → *Run workflow* (rien n'est publié ; l'installateur est téléchargeable
dans les artefacts du run). Coche « génération 3D complète » pour exécuter en plus une vraie génération sur processeur
(télécharge environ 2 Go de modèles ; plusieurs minutes). Cette étape remplace temporairement le logiciel installé par une
version **non compilée** acceptant une licence de développement (`tools/dev_license.py`) : la version commerciale, elle, ne
s'ouvre pas sans vraie licence, y compris sur le serveur de CI.

## Validation sur un vrai ordinateur

Le serveur de CI n'a pas de carte graphique : il prouve que l'installation, les raccourcis, l'interface et la
désinstallation fonctionnent, pas que le calcul sur carte NVIDIA marche. Avant chaque publication, sur un PC avec carte NVIDIA :

- [ ] Lancer l'installateur, aller au bout (la fenêtre de commandes montre l'avancement ; 10 à 30 minutes).
- [ ] Menu Démarrer → **Diagnostic** : « RESULTAT : tout est prêt » et « CUDA disponible » avec le nom de la carte.
- [ ] Ouvrir le logiciel, charger `tests/data/sample.png`, générer : le premier calcul télécharge les modèles (environ 2 Go).
- [ ] Vérifier le modèle dans la visionneuse : bonne orientation (avant vers l'écran), couleurs plausibles.
- [ ] Exporter en `.glb` et `.obj` avec texture ; ouvrir le `.glb` dans un autre outil (Windows 3D Viewer, Blender).
- [ ] Menu Démarrer → **Réparer l'installation**, puis relancer le logiciel.
- [ ] Mettre à jour : lancer l'installateur de la version suivante par-dessus ; le logiciel et les réglages sont conservés.
- [ ] Désinstaller (Paramètres → Applications) ; répondre « Non » à la question sur les modèles, puis réinstaller : pas de
  nouveau téléchargement de 2 Go.
- [ ] Sur un compte Windows dont le nom contient un accent ou une espace : l'installation et la génération fonctionnent.

## Construire en local (Windows)

```powershell
py -3.11 -m venv .venv ; .venv\Scripts\activate
python -m pip install build Cython        # la compilation demande aussi les outils C++ de Visual Studio (Build Tools)
$env:I3D_COMPILE_LICENSE = "1"
$env:I3D_LICENSE_PUBKEYS = "k1=<clé publique base64>"
$env:I3D_LICENSE_URL = "https://licence.ton-domaine.fr"
python -m build --wheel --no-isolation
python packaging/build_stage.py --wheel (Get-ChildItem dist\imagevers3d-*.whl).FullName --import-check
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.0 packaging\windows\ImageVers3D.iss
```

Pour un essai sans licence ni compilation (développement seulement, **ne jamais distribuer le résultat**) :
`python -m build --wheel` puis `build_stage.py --allow-uncompiled`.

Résultat : `build\installer\ImageVers3D-Setup-0.1.0.exe`. Installation de test sans carte NVIDIA :
`ImageVers3D-Setup-0.1.0.exe /TORCH=cpu`. Autres paramètres utiles : `/VERYSILENT`, `/DIR=C:\i3d`, `/LOG=journal.txt`
(le journal des composants est `<dossier>\logs\setup_runtime.log`).

## Mettre à jour les versions épinglées

| Quoi | Où | Comment vérifier |
|---|---|---|
| PyTorch | `packaging/windows/versions.json` | la CI installe cette version (processeur) ; la version CUDA doit exister sur l'index `cu128` |
| uv | `versions.json` (version + SHA-256) | somme publiée dans les assets de la release uv (`…zip.sha256`) |
| TripoSR | `versions.json` (commit) | relire le diff du dépôt amont, relancer les tests et une génération réelle |
| Autres dépendances | `requirements/main.in`, puis régénérer `windows-py311.lock` | CI + rapport de licences |

Un changement de version majeure de Python (3.11 → 3.12) demande de régénérer le verrou et de renommer `windows-py311.lock`.

## Signature du code (non configurée)

L'installateur n'est pas signé : Windows SmartScreen affichera un avertissement
([DISTRIBUTION.md](DISTRIBUTION.md#signature-et-smartscreen)). Quand un certificat ou un compte de signature est disponible,
la signature se place **entre la compilation et le test d'installation** du workflow `release.yml`, sur
`build\installer\ImageVers3D-Setup-*.exe`, avec les secrets du dépôt (jamais dans le code). Rien de cela n'a été essayé ici :
suis la documentation du service choisi.

## En cas d'échec de la CI

- **Inno Setup : `French.isl` introuvable ou option inconnue** : ouvre le journal de l'étape de compilation ; la version
  installée sur le serveur peut différer de la tienne. Corrige le script ou installe une version précise avec `choco`.
- **`setup_runtime.bat` échoue** : le journal complet est affiché dans le groupe « Journal des composants » de l'étape de test et
  téléchargé dans l'artefact `journaux-installation`.
- **Version de PyTorch introuvable** : vérifie qu'elle existe pour Windows / Python 3.11 sur l'index concerné.
- **« Variables du dépôt manquantes » / « Wheel refusée »** : voir [LICENSING.md](LICENSING.md#construire-une-version-commerciale) ;
  une wheel « Python pur » (`py3-none-any`) signifie que la compilation des modules de licence n'a pas eu lieu.
- **Compilation Cython sous Windows : `Microsoft Visual C++ 14.0 or greater is required`** : le serveur Windows de GitHub en
  dispose normalement ; en local, installe les « Build Tools pour Visual Studio » (composant C++). Jamais exécuté ici.
- **Test d'installation : raccourci manquant** : le nom des raccourcis est défini dans la section `[Icons]` du script Inno.
