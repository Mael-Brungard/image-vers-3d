from pathlib import Path

from imagevers3d import paths


def test_home_variable_wins(tmp_path):
    assert paths.find_app_root({"IMAGEVERS3D_HOME": str(tmp_path)}, prefix="/x/runtime/main") == tmp_path.resolve()


def test_installed_layout(tmp_path):
    venv = tmp_path / "ImageVers3D" / "runtime" / "main"
    venv.mkdir(parents=True)
    assert paths.find_app_root({}, prefix=str(venv)) == (tmp_path / "ImageVers3D").resolve()


def test_development_layout(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    package = tmp_path / "src" / "imagevers3d"
    package.mkdir(parents=True)
    other_venv = tmp_path / ".venv"
    other_venv.mkdir()
    assert paths.find_app_root({}, prefix=str(other_venv), package_dir=package) == tmp_path


def test_data_dir_by_platform(tmp_path):
    assert paths.find_data_dir({"IMAGEVERS3D_DATA": str(tmp_path)}) == tmp_path
    windows = paths.find_data_dir({"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, platform="win32")
    assert windows.name == "ImageVers3D"
    linux = paths.find_data_dir({"XDG_DATA_HOME": "/data"}, platform="linux")
    assert linux == Path("/data/imagevers3d")


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
