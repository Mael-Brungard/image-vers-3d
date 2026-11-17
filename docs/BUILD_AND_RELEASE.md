# Construire et publier une version

## Publier (le chemin normal)

1. Mets à jour `version` dans `pyproject.toml` et ajoute la section correspondante dans `CHANGELOG.md`.
2. Fusionne sur `main` (le workflow **CI** doit être vert).
3. Crée et pousse le tag :
   ```
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Le workflow **Release** (`.github/workflows/release.yml`) tourne sur un serveur Windows :
   1. vérifie que le tag correspond à la version de `pyproject.toml` ;
   2. construit le logiciel (wheel) puis le dossier de l'installateur (`packaging/build_stage.py` : uv vérifié par SHA-256,
      TripoSR au commit épinglé) ;
   3. compile l'installateur avec Inno Setup ;
   4. **l'installe en silencieux** avec PyTorch sur processeur (`/TORCH=cpu`), exécute le diagnostic, importe l'interface,
      contrôle les raccourcis ;
   5. produit le rapport des licences des composants installés ;
   6. **le désinstalle** et contrôle que `runtime\` a disparu ;
   7. calcule les sommes SHA-256 ;
   8. dépose `ThreeRex-Setup-x.y.z.exe`, `SHA256SUMS.txt` et `licences-composants.txt` dans une **release en brouillon**.
5. Ouvre la release en brouillon sur GitHub, lis le rapport de licences, **teste l'installateur sur un vrai ordinateur**
   (liste ci-dessous), puis publie.

Pour essayer sans tag : onglet *Actions* → *Release* → *Run workflow* (rien n'est publié ; l'installateur est téléchargeable
dans les artefacts du run). Coche « génération 3D complète » pour exécuter en plus une vraie génération sur processeur
(télécharge environ 2 Go de modèles ; plusieurs minutes).

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
python -m pip install build
python -m build --wheel
python packaging/build_stage.py --wheel dist\threerex-0.1.0-py3-none-any.whl
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.0 packaging\windows\ThreeRex.iss
```

Résultat : `build\installer\ThreeRex-Setup-0.1.0.exe`. Installation de test sans carte NVIDIA :
`ThreeRex-Setup-0.1.0.exe /TORCH=cpu`. Autres paramètres utiles : `/VERYSILENT`, `/DIR=C:\i3d`, `/LOG=journal.txt`
(le journal des composants est `<dossier>\logs\setup_runtime.log`).

## Mettre à jour les versions épinglées

| Quoi | Où | Comment vérifier |
|---|---|---|
| PyTorch | `packaging/windows/versions.json` | la CI installe cette version (processeur) ; la version CUDA doit exister sur l'index `cu128` |
| uv | `versions.json` (version + SHA-256) | somme publiée dans les assets de la release uv (`…zip.sha256`) |
| TripoSR | `versions.json` (commit) | relire le diff du dépôt amont, relancer les tests et une génération réelle |
| Autres dépendances | `requirements/main.in`, puis régénérer `windows-py311.lock` | CI + rapport de licences |

Un changement de version majeure de Python (3.11 → 3.12) demande de régénérer le verrou et de renommer `windows-py311.lock`.

## Signature du code (inutile pour un usage personnel)

L'installateur n'est pas signé : Windows SmartScreen affichera un avertissement la première fois (« Informations
complémentaires » puis « Exécuter quand même »). Pour un logiciel qu'on installe soi-même, c'est sans conséquence. Si le
logiciel était un jour diffusé à d'autres, il faudrait signer le fichier (certificat de signature de code, par exemple Azure
Artifact Signing selon l'éligibilité) entre la compilation et le test d'installation du workflow `release.yml`.

## En cas d'échec de la CI

- **Inno Setup : `French.isl` introuvable ou option inconnue** : ouvre le journal de l'étape de compilation ; la version
  installée sur le serveur peut différer de la tienne. Corrige le script ou installe une version précise avec `choco`.
- **`setup_runtime.bat` échoue** : le journal complet est affiché dans le groupe « Journal des composants » de l'étape de test et
  téléchargé dans l'artefact `journaux-installation`.
- **Version de PyTorch introuvable** : vérifie qu'elle existe pour Windows / Python 3.11 sur l'index concerné.
- **Test d'installation : raccourci manquant** : le nom des raccourcis est défini dans la section `[Icons]` du script Inno.
