"""Interface de licence : écran d'activation, essai, pastille, blocage des calculs, désactivation. Rendu hors écran,
« faux serveur » signant avec une clé de test ; le moteur 3D est factice."""

import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("OpenGL")
pytest.importorskip("trimesh")

from licensing_helpers import FakeServer, make_keypair  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from imagevers3d import _licproto as proto  # noqa: E402
from imagevers3d import license as lic  # noqa: E402
from imagevers3d import license_ui, studio, theme  # noqa: E402

DAY = 86400
T0 = 1_800_000_000
KEY_BODY = proto.key_body_from_secret(b"s" * 32, "lic-ui")
KEY = proto.display_key(KEY_BODY)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


class QuietEngine:
    def triposg_ready(self):
        return False

    def device_label(self):
        return "GPU : TEST"


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    theme.apply_theme(instance, "dark")
    return instance


@pytest.fixture()
def env(tmp_path, app, monkeypatch):
    dialogs = []
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, _n=name, **k: dialogs.append(_n)))
    opened = []
    monkeypatch.setattr(license_ui, "open_url", opened.append)
    monkeypatch.setattr(lic._license_keys, "SERVER_URL", "https://licence.example.test")
    monkeypatch.setattr(lic._license_keys, "BUY_URL", "https://buy.example.test/i3d")

    private, public = make_keypair()
    clock = Clock()
    server = FakeServer(private, KEY_BODY)
    server.clock = clock
    manager = lic.LicenseManager(tmp_path / "data", clock=clock, device_id=proto.make_device_id("ui-test"), client=server, keys={"k1": public})
    lic.set_manager(manager)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    win = studio.MainWindow(QuietEngine(), settings)
    win.show()
    QTest.qWait(50)
    state = type("Env", (), {"win": win, "manager": manager, "clock": clock, "server": server, "dialogs": dialogs, "opened": opened, "private": private})
    yield state
    win.close()
    lic.set_manager(None)  # retour à la licence de développement de tests/conftest.py


def wait_until(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        QTest.qWait(20)
    return False


def type_key(win, text):
    win.gate.key_input.setText(text)


# ------------------------------------------------------------------ sans licence

def test_first_launch_shows_the_gate_instead_of_the_studio(env):
    win = env.win
    assert win._gate_visible() and win.stack.currentWidget() is win.gate
    assert win.gate.title.text() == "Bienvenue dans Image vers 3D"
    assert win.gate.btn_trial.isVisibleTo(win.gate) and win.gate.btn_activate.isVisibleTo(win.gate)
    assert not win.gate.btn_close.isVisibleTo(win.gate)  # pas de retour possible sans licence
    assert win.gate.btn_buy.isVisibleTo(win.gate) and win.gate.btn_account.isVisibleTo(win.gate)
    assert not win.gate.btn_deactivate.isVisibleTo(win.gate)
    assert not env.dialogs


def test_gate_has_accessible_names_and_a_single_primary_action(env):
    gate = env.win.gate
    assert gate.key_input.accessibleName() == "Clé de licence" and gate.title.accessibleName()
    primaries = [b for b in gate.findChildren(license_ui.QPushButton) if b.property("kind") == "primary" and b.isVisibleTo(gate)]
    assert [b.objectName() for b in primaries] == ["btn_activate"]


def test_shortcuts_and_drops_do_nothing_behind_the_gate(env, monkeypatch):
    win = env.win
    called = []
    monkeypatch.setattr(win, "on_open", lambda: called.append("open"))
    win._if_studio(win.on_open)
    assert called == []
    win.stack.setCurrentWidget(win._root)
    win._if_studio(win.on_open)
    assert called == ["open"]


def test_tasks_cannot_start_without_a_licence(env):
    win = env.win
    started = []
    win.run_task(lambda progress, partial: started.append(1), lambda r: None)
    QTest.qWait(100)
    assert win._task is None and started == [] and win._gate_visible()


def test_engine_methods_refuse_to_work_without_a_licence(env):
    engine = studio.Engine()
    with pytest.raises(lic.LicenseError):
        engine.preprocess(None, True, 0.85, lambda text: None)
    with pytest.raises(lic.LicenseError):
        engine.generate(None, 256, lambda text: None)
    with pytest.raises(lic.LicenseError):
        engine.export(None, None, "x.glb", False, lambda text: None)


# ------------------------------------------------------------------ essai

def test_starting_the_trial_unlocks_the_studio_and_shows_the_chip(env):
    win = env.win
    win.gate.btn_trial.click()
    assert wait_until(lambda: not win._gate_visible())
    assert win.chip_trial.isVisibleTo(win.chip_trial.parentWidget()) and win.chip_trial.text() == "Essai : 7 j"
    assert env.manager.status().state == "trial"
    assert "Essai gratuit de 7 jours" in win.viewport.toast.message()


def test_trial_chip_opens_the_gate_in_manage_mode_and_escape_returns(env):
    win = env.win
    win.gate.btn_trial.click()
    assert wait_until(lambda: not win._gate_visible())
    win.chip_trial.click()
    assert win._gate_visible() and win.gate.btn_close.isVisibleTo(win.gate)
    assert not win.gate.btn_trial.isVisibleTo(win.gate)  # déjà en essai
    QTest.keyClick(win, Qt.Key.Key_Escape)
    assert not win._gate_visible()


def test_trial_ending_while_the_app_is_open_closes_the_studio(env):
    win = env.win
    win.gate.btn_trial.click()
    assert wait_until(lambda: not win._gate_visible())
    env.clock.now += 7 * DAY + 5
    win._check_license()  # le minuteur fait la même chose chaque minute
    assert win._gate_visible() and win.gate.title.text() == "Ton essai gratuit est terminé"
    assert not win.gate.btn_trial.isVisibleTo(win.gate) and not win.chip_trial.isVisible()
    assert not win.gate.btn_close.isVisibleTo(win.gate)


def test_clock_rollback_is_explained_in_the_gate(env):
    win = env.win
    win.gate.btn_trial.click()
    assert wait_until(lambda: not win._gate_visible())
    env.clock.now += 3 * DAY
    win._check_license()
    env.clock.now -= 2 * DAY
    win._check_license()
    assert win._gate_visible() and "heure" in win.gate.title.text().lower()


# ------------------------------------------------------------------ activation

def test_malformed_key_is_reported_inline_without_contacting_the_server(env):
    gate = env.win.gate
    type_key(env.win, "pas une clé")
    gate.btn_activate.click()
    assert gate.message.isVisibleTo(gate) and "bon format" in gate.message.text()
    assert gate.message.property("role") == "danger" and gate.key_input.property("invalid") == "true"
    assert not env.server.calls and not env.dialogs
    type_key(env.win, "I3D-")  # on retape : le marquage d'erreur disparaît
    assert gate.key_input.property("invalid") == "false"


def test_unknown_key_shows_the_server_message_and_stays_on_the_gate(env):
    gate = env.win.gate
    type_key(env.win, proto.display_key(proto.key_body_from_secret(b"z" * 32, "autre")))
    gate.btn_activate.click()
    assert wait_until(lambda: gate.message.text() == "Clé inconnue.")
    assert env.win._gate_visible() and gate.message.property("role") == "danger" and gate.btn_activate.isEnabled()


def test_valid_key_activates_and_opens_the_studio(env):
    win = env.win
    type_key(win, KEY.lower())
    win.gate.key_input.returnPressed.emit()  # la touche Entrée suffit
    assert wait_until(lambda: not win._gate_visible())
    assert env.manager.status().state == "licensed" and not win.chip_trial.isVisible()
    assert win.gate.key_input.text() == "" and "Licence activée" in win.viewport.toast.message()


def test_network_failure_is_explained_and_can_be_retried(env):
    win = env.win

    class Offline:
        def post(self, path, body):
            raise lic.LicenseError("network", "Impossible de joindre le serveur de licence. Vérifie ta connexion Internet puis réessaie.")

    online = env.manager._client
    env.manager._client = Offline()
    type_key(win, KEY)
    win.gate.btn_activate.click()
    assert wait_until(lambda: "connexion Internet" in win.gate.message.text())
    assert win._gate_visible() and win.gate.btn_activate.isEnabled()
    env.manager._client = online
    win.gate.btn_activate.click()
    assert wait_until(lambda: not win._gate_visible())


def test_buttons_are_disabled_while_the_request_runs(env):
    win = env.win
    release = []

    class Slow:
        def post(self, path, body):
            while not release:
                time.sleep(0.01)
            return env.server.post(path, body)

    env.manager._client = Slow()
    type_key(win, KEY)
    win.gate.btn_activate.click()
    assert wait_until(lambda: not win.gate.btn_activate.isEnabled())
    assert not win.gate.btn_trial.isEnabled() and win.gate.progress.isVisibleTo(win.gate)
    release.append(1)
    assert wait_until(lambda: not win._gate_visible())


def test_buy_and_account_links_open_the_browser(env):
    win = env.win
    win.gate.btn_buy.click()
    win.gate.btn_account.click()
    assert env.opened == ["https://buy.example.test/i3d", "https://licence.example.test/"]


# ------------------------------------------------------------------ licence active

def activate(env):
    type_key(env.win, KEY)
    env.win.gate.btn_activate.click()
    assert wait_until(lambda: not env.win._gate_visible())


def test_licensed_gate_is_a_management_page(env):
    win = env.win
    activate(env)
    win.menu.btn_license.click()
    gate = win.gate
    assert win._gate_visible() and gate.title.text() == "Licence active"
    assert not gate.key_section.isVisibleTo(gate) and gate.btn_deactivate.isVisibleTo(gate) and gate.btn_close.isVisibleTo(gate)
    gate.btn_close.click()
    assert not win._gate_visible()


def test_deactivation_needs_a_second_click_then_blocks_the_app(env):
    win = env.win
    activate(env)
    win.on_open_license()
    gate = win.gate
    gate.btn_deactivate.click()
    assert gate.btn_deactivate.text().startswith("Confirmer") and gate.deactivate_hint.isVisibleTo(gate)
    assert env.manager.status().state == "licensed"  # un seul clic ne change rien
    gate.btn_deactivate.click()
    assert wait_until(lambda: env.manager.status().state == "none")
    assert wait_until(lambda: win._gate_visible() and not win.gate.btn_close.isVisibleTo(win.gate))
    assert [c[0] for c in env.server.calls].count("/v1/deactivate") == 1


def test_failed_deactivation_keeps_the_licence_and_says_why(env):
    win = env.win
    activate(env)

    class Refuses:
        def post(self, path, body):
            raise lic.LicenseError("transfer_limit", "Tu as déjà libéré 3 places cette année.")

    env.manager._client = Refuses()
    win.on_open_license()
    win.gate.btn_deactivate.click()
    win.gate.btn_deactivate.click()
    assert wait_until(lambda: "libéré 3 places" in win.gate.message.text())
    assert env.manager.status().state == "licensed" and win.gate.btn_deactivate.text() == "Désactiver cet ordinateur"


def test_licence_ending_during_a_task_shows_the_gate_not_an_error_panel(env):
    win = env.win
    activate(env)
    state = {}

    def job(progress, partial):
        # la licence disparaît en plein calcul (fichier effacé, jeton révoqué…) : le calcul suivant lève LicenseError
        env.manager.state_path.unlink()
        env.manager._verified.clear()
        lic.require()

    win.run_task(job, lambda r: state.setdefault("done", True))
    assert wait_until(lambda: win._gate_visible())
    assert "done" not in state and win._error is None
    assert win.viewport.page_name() != win.viewport.ERROR
