# Développement

## Poste de développement (Windows, ou Linux pour les tests)

```powershell
git clone https://github.com/Mael-Brungard/image-vers-3d.git
cd image-vers-3d
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

PyTorch s'installe à part, depuis l'index qui correspond à ta carte :

```powershell
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cu128     # carte NVIDIA
python -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu       # sans carte NVIDIA
```

Puis récupère TripoSR au commit épinglé et vérifie l'installation :

```powershell
python scripts/fetch_vendor.py
python -m threerex.diagnostic
python -m threerex            # lance l'application
```

(La version de PyTorch à utiliser est celle de `packaging/windows/versions.json`.)

## Tests

```powershell
python -m pytest            # tout (environ 20 secondes) ; PyTorch n'est pas nécessaire
ruff check .                # analyse statique
```

- `tests/test_*.py` : tests unitaires (chemins, remplaçant de `torchmcubes`, rapport de licences, garde-fous de licence,
  contrôles du paquetage).
- `tests/scenarios/*.py` : scénarios de bout en bout, lancés chacun dans un processus séparé par `tests/test_scenarios.py`
  (ils se lancent aussi à la main : `python tests/scenarios/studio_ui.py` ; avec `THREEREX_TEST_OUT=<dossier>`, il y laisse
  des captures de chaque état de l'interface). Ils utilisent un faux moteur d'IA : aucune carte
  graphique ni modèle téléchargé.
- Les tests n'écrivent jamais dans ton dossier de données : `tests/conftest.py` pointe `THREEREX_DATA` vers un dossier
  temporaire et force Qt en mode hors écran.

**Ce que les tests ne couvrent pas** : le calcul réel de TripoSR sur carte NVIDIA, la visionneuse OpenGL sur un vrai affichage,
l'installateur sur un ordinateur d'utilisateur. Voir [BUILD_AND_RELEASE.md](BUILD_AND_RELEASE.md#validation-sur-un-vrai-ordinateur).

## Conventions

- Style : `ruff` (règles `E4, E7, E9, F`, 120 colonnes). Le texte visible par l'utilisateur est en français.
- Un nouveau chemin de fichier passe par `paths.py`, jamais en dur.
- Toute dépendance nouvelle : l'ajouter à `requirements/main.in`, régénérer le verrou
  (`uv pip compile requirements/main.in --python-version 3.11 --python-platform windows --generate-hashes -o requirements/windows-py311.lock`),
  puis **vérifier sa licence** (`scripts/licences_report.py`, [LICENSES.md](LICENSES.md)).
- Aucun appel à `rembg` sans modèle nommé : un test l'impose.
