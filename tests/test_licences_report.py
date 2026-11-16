import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "licences_report.py"
spec = importlib.util.spec_from_file_location("licences_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


@pytest.mark.parametrize("licence", ["MIT", "BSD-3-Clause", "Apache-2.0", "HPND", "MIT License", "Apache-2.0 OR BSD-2-Clause", "MIT AND Python-2.0"])
def test_permissive_licences_pass(licence):
    assert report.assess(licence) is None


@pytest.mark.parametrize("licence", ["CC BY-NC 4.0", "Non-Commercial research use only", "AGPL-3.0", "GPL-3.0", "GNU General Public License v3"])
def test_blocking_licences_are_flagged(licence):
    verdict = report.assess(licence)
    assert verdict is not None and verdict[0] == "verifier"


def test_lgpl_is_a_condition_not_a_blocker():
    assert report.assess("LGPL-3.0-only")[0] == "conditions"
    assert report.assess("GNU Lesser General Public License v3 (LGPLv3)")[0] == "conditions"


def test_dual_licence_choosing_lgpl():
    assert report.assess("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only")[0] == "conditions"


def test_dual_licence_gpl_only_is_flagged():
    assert report.assess("GPL-2.0-only OR GPL-3.0-only")[0] == "verifier"


class FakeDistribution:
    def __init__(self, name, version, licence):
        self.version = version
        self.metadata = _FakeMetadata({"Name": name, "License-Expression": licence})


class _FakeMetadata(dict):
    def get_all(self, key):
        return None


def test_report_goes_to_the_repository_licences_folder_and_skips_our_own_package(monkeypatch, tmp_path, capsys):
    """CI : `licences\\licences_<env>.txt` à la racine du dépôt ; le logiciel lui-même n'est pas « à vérifier »."""
    assert report.ROOT == Path(__file__).resolve().parents[1]
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(report.metadata, "distributions", lambda: [
        FakeDistribution("imagevers3d", "0.1.0", "LicenseRef-Proprietary"),
        FakeDistribution("torch", "2.0", "BSD-3-Clause"),
        FakeDistribution("gplthing", "1.0", "GPL-3.0"),
        FakeDistribution("mystere", "1.0", ""),
    ])
    assert report.main() == 0
    out = capsys.readouterr().out
    assert "A verifier : 1" in out and "gplthing" in out and "mystere" in out and "imagevers3d 0.1.0 (" not in out
    written = list((tmp_path / "licences").glob("licences_*.txt"))
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "imagevers3d 0.1.0  |  LicenseRef-Proprietary" in text, "il reste listé, mais sans alerte"
    assert "gplthing 1.0  |  GPL-3.0  ->" in text
