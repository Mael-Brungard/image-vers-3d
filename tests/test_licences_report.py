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
