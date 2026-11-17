from pathlib import Path

from threerex import paths


def test_home_variable_wins(tmp_path):
    assert paths.find_app_root({"THREEREX_HOME": str(tmp_path)}, prefix="/x/runtime/main") == tmp_path.resolve()


def test_installed_layout(tmp_path):
    venv = tmp_path / "ThreeRex" / "runtime" / "main"
    venv.mkdir(parents=True)
    assert paths.find_app_root({}, prefix=str(venv)) == (tmp_path / "ThreeRex").resolve()


def test_development_layout(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    package = tmp_path / "src" / "threerex"
    package.mkdir(parents=True)
    other_venv = tmp_path / ".venv"
    other_venv.mkdir()
    assert paths.find_app_root({}, prefix=str(other_venv), package_dir=package) == tmp_path


def test_data_dir_by_platform(tmp_path):
    assert paths.find_data_dir({"THREEREX_DATA": str(tmp_path)}) == tmp_path
    windows = paths.find_data_dir({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, platform="win32")
    assert windows.name == "ThreeRex"
    linux = paths.find_data_dir({"XDG_DATA_HOME": "/data"}, platform="linux")
    assert linux == Path("/data/threerex")


def test_venv_python_prefers_runtime(tmp_path):
    runtime = tmp_path / "runtime" / "triposg" / "Scripts"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_text("", encoding="utf-8")
    dev = tmp_path / ".venv-triposg" / "Scripts"
    dev.mkdir(parents=True)
    (dev / "python.exe").write_text("", encoding="utf-8")
    assert paths.venv_python("triposg", tmp_path, windows=True) == runtime / "python.exe"


def test_venv_python_falls_back_to_dev_environment(tmp_path):
    dev = tmp_path / ".venv-main" / "bin"
    dev.mkdir(parents=True)
    (dev / "python").write_text("", encoding="utf-8")
    assert paths.venv_python("main", tmp_path, windows=False) == dev / "python"


def test_venv_python_missing_returns_installer_location(tmp_path):
    assert paths.venv_python("main", tmp_path, windows=True) == tmp_path / "runtime" / "main" / "Scripts" / "python.exe"


def test_user_data_never_inside_app_root():
    assert paths.APP_ROOT not in paths.DATA_DIR.parents


def test_legacy_data_dir_names():
    assert paths.legacy_data_dir({"THREEREX_DATA": "x"}) is None
    assert paths.legacy_data_dir({"LOCALAPPDATA": r"C:\L"}, platform="win32").name == "ImageVers3D"
    assert paths.legacy_data_dir({"XDG_DATA_HOME": "/d"}, platform="linux") == Path("/d/imagevers3d")


def test_old_data_folder_is_moved_with_its_models(tmp_path):
    old, new = tmp_path / "ImageVers3D", tmp_path / "ThreeRex"
    (old / "engines" / "trellis" / "models" / "q4").mkdir(parents=True)
    (old / "engines" / "trellis" / "models" / "q4" / "ss_flow.gguf").write_bytes(b"x" * 10)
    (old / "logs").mkdir()
    assert paths.migrate_legacy_data(new, old)
    assert (new / "engines" / "trellis" / "models" / "q4" / "ss_flow.gguf").read_bytes() == b"x" * 10 and not old.exists()


def test_migration_replaces_an_empty_new_folder_but_never_overwrites_real_data(tmp_path):
    old, new = tmp_path / "ImageVers3D", tmp_path / "ThreeRex"
    (old / "models").mkdir(parents=True)
    (old / "models" / "m.bin").write_bytes(b"1")
    (new / "logs").mkdir(parents=True)  # créé par un lancement précédent, sans fichier
    assert paths.migrate_legacy_data(new, old) and (new / "models" / "m.bin").exists()
    again_old = tmp_path / "ImageVers3D"
    again_old.mkdir()
    (again_old / "x").write_bytes(b"2")
    assert not paths.migrate_legacy_data(new, again_old) and (again_old / "x").exists()  # le nouveau a des fichiers


def test_migration_without_old_folder_does_nothing(tmp_path):
    assert not paths.migrate_legacy_data(tmp_path / "ThreeRex", tmp_path / "absent")
    assert not paths.migrate_legacy_data(tmp_path / "ThreeRex", None)
    assert not (tmp_path / "ThreeRex").exists()
