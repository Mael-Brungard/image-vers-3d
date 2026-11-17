"""Système de design ThreeRex : jetons, contrastes, feuille de style, icônes et composants."""

import colorsys
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from threerex import icons, theme, widgets  # noqa: E402
from threerex.theme import TOKENS, Motion, Theme, build_qss, contrast  # noqa: E402

# La vraie fonction, gardée avant que conftest.py ne la remplace pour chaque test (la CI Windows a les animations coupées).
REAL_SYSTEM_MOTION = theme.system_prefers_reduced_motion
REPO = Path(__file__).resolve().parents[1]
MODES = ("dark",)
SURFACES = ("bg-deep", "bg-app", "bg-viewport", "bg-panel", "bg-raised")


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    theme.apply_theme(instance, "dark", 1.0)
    return instance


@pytest.fixture(scope="module")
def stage(app):
    """Support visible auquel on accroche les widgets qui s'animent. Un widget SANS parent qu'on lâche pendant son
    animation est détruit par Python au milieu d'un signal de sa propre animation : Qt plante au tour suivant de la boucle
    d'événements (dans l'application, tout widget a un parent, le cas n'existe pas)."""
    holder = QWidget()
    holder.resize(700, 300)
    holder.show()
    yield holder
    holder.close()
    holder.deleteLater()


@pytest.fixture(autouse=True)
def _motion_on():
    Motion.system_reduced = False
    Motion.user_reduced = False
    yield
    Motion.system_reduced = False
    Motion.user_reduced = False


# ---- jetons ---------------------------------------------------------------------------------------------------------
def test_tokens_match_design_file():
    """design/tokens.json est la source commune avec Figma : le code ne doit pas en dériver."""
    data = json.loads((REPO / "design" / "tokens.json").read_text(encoding="utf-8"))
    for mode in MODES:
        assert TOKENS[mode] == data[mode], mode


def test_theme_is_dark_only():
    """L'identité (halos, lueurs) n'a de sens que sur fond sombre : un seul thème, quoi qu'on demande."""
    assert tuple(TOKENS) == ("dark",) and theme.THEME_MODES == ("dark",)
    for asked in ("light", "system", "n'importe quoi", "dark"):
        assert theme.resolve_mode(asked) == "dark"
        assert Theme(asked).mode == "dark"


def _hue(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def test_identity_is_orange_and_violet():
    c = TOKENS["dark"]
    for key in ("accent", "accent-hover", "accent-pressed", "accent-text", "accent-ui", "focus"):
        assert 10 <= _hue(c[key]) <= 40, f"{key} n'est pas orange"
    for key in ("violet", "violet-hover", "violet-text", "violet-deep", "violet-soft"):
        assert 245 <= _hue(c[key]) <= 275, f"{key} n'est pas violet"


@pytest.mark.parametrize("mode", MODES)
def test_no_pure_black(mode):
    assert "#000000" not in {v.upper() for v in TOKENS[mode].values()}


# ---- contrastes -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("surface", SURFACES)
def test_text_contrast(mode, surface):
    c = TOKENS[mode]
    assert contrast(c["text"], c[surface]) >= 7, "texte principal"
    assert contrast(c["text-secondary"], c[surface]) >= 4.5
    assert contrast(c["text-muted"], c[surface]) >= 4.5
    assert contrast(c["accent-text"], c[surface]) >= 4.5, "texte d'accent"
    assert contrast(c["violet-text"], c[surface]) >= 4.5, "texte violet"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("surface", ("bg-app", "bg-panel", "bg-raised"))
def test_component_boundaries_contrast(mode, surface):
    """Contours des contrôles, pastille d'accent et anneau de focus : 3:1 au moins (WCAG 1.4.11)."""
    c = TOKENS[mode]
    assert contrast(c["border-strong"], c[surface]) >= 3
    assert contrast(c["accent-ui"], c[surface]) >= 3
    assert contrast(c["focus"], c[surface]) >= 3


@pytest.mark.parametrize("mode", MODES)
def test_status_colors_readable(mode):
    c = TOKENS[mode]
    for surface in ("bg-panel", "bg-raised", "bg-viewport"):
        for key in ("success", "danger", "warning", "info"):
            assert contrast(c[key], c[surface]) >= 4.5, f"{key} sur {surface}"


@pytest.mark.parametrize("mode", MODES)
def test_primary_button_contrast(mode):
    c = TOKENS[mode]
    for key in ("accent", "accent-hover", "accent-pressed"):
        assert contrast(c["on-accent"], c[key]) >= 4.5, key
    assert contrast(c["on-accent"], c["accent"]) >= 7
    assert contrast(c["text"], c["accent-soft"]) >= 7, "libellé du segment actif"
    assert contrast(c["accent-text"], c["accent-soft"]) >= 4.5, "pastille « Recommandé »"
    assert contrast(c["violet-text"], c["violet-soft"]) >= 4.5, "pastille violette"
    assert contrast(c["text"], c["violet-soft"]) >= 7


def test_contrast_function_known_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)


# ---- feuille de style -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("scale", theme.TEXT_SCALES)
def test_qss_builds_without_leftovers(mode, scale):
    qss = build_qss(Theme(mode, scale))
    assert "{c[" not in qss and "{p(" not in qss and "None" not in qss
    assert qss.count("{") == qss.count("}")


def test_no_text_smaller_than_13px():
    qss = build_qss(Theme("dark", 1.0))
    sizes = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", qss)]
    assert sizes and min(sizes) >= 13


def test_controls_are_44px_and_scale_with_text():
    assert "min-height: 44px" in build_qss(Theme("dark", 1.0))
    assert "min-height: 57px" in build_qss(Theme("dark", 1.3))  # 44 x 1,3 arrondi


def test_theme_px_never_below_one():
    assert Theme("dark", 1.0).px(0.1) == 1


def test_fonts_are_bundled_and_load(app):
    for name in theme.FONT_FILES:
        font = REPO / "src" / "threerex" / "assets" / "fonts" / name
        assert font.is_file(), name
        assert QFontDatabase.addApplicationFont(str(font)) >= 0, name
    assert (REPO / "src" / "threerex" / "assets" / "fonts" / "OFL.txt").is_file()
    assert (REPO / "src" / "threerex" / "assets" / "LUCIDE-LICENSE.txt").is_file()


def test_fonts_are_declared_as_package_data():
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "assets/fonts/*" in pyproject


def test_apply_theme_notifies_and_scales(app):
    seen = []
    theme.bus.changed.connect(lambda: seen.append(theme.current().scale))
    theme.apply_theme(app, "dark", 1.15)
    assert theme.current().mode == "dark" and theme.current().scale == 1.15
    theme.apply_theme(app, "dark", 1.0)
    assert seen[-2:] == [1.15, 1.0]


# ---- mouvement ------------------------------------------------------------------------------------------------------
def test_motion_can_be_reduced_by_user_or_system():
    assert Motion.enabled() and Motion.ms(200) == 200
    Motion.user_reduced = True
    assert not Motion.enabled() and Motion.ms(200) == 0
    Motion.user_reduced = False
    Motion.system_reduced = True
    assert Motion.ms(200) == 0


def test_system_motion_follows_the_windows_animation_setting(monkeypatch):
    """« Afficher les animations dans Windows » coupé (SPI_GETCLIENTAREAANIMATION = 0) : mouvement réduit. Ailleurs : jamais."""
    import ctypes
    import types

    def fake_windll(value: int):
        def spi(action, param, ref, flags):
            assert action == 0x1042
            ref._obj.value = value
            return 1

        return types.SimpleNamespace(user32=types.SimpleNamespace(SystemParametersInfoW=spi))

    with monkeypatch.context() as m:
        m.setattr(theme.sys, "platform", "win32")
        m.setattr(ctypes, "windll", fake_windll(0), raising=False)
        assert REAL_SYSTEM_MOTION() is True
        m.setattr(ctypes, "windll", fake_windll(1), raising=False)
        assert REAL_SYSTEM_MOTION() is False
        m.setattr(theme.sys, "platform", "linux")
        assert REAL_SYSTEM_MOTION() is False
    assert isinstance(REAL_SYSTEM_MOTION(), bool)  # sous Windows, l'appel réel ne plante pas


def test_tests_do_not_depend_on_the_machine_animation_setting():
    """Garde-fou de conftest.py : même si la machine coupe les animations, l'interface testée les garde."""
    Motion.refresh(False, False)
    assert Motion.enabled() and Motion.ambient()


def test_gpu_name_is_shortened_but_the_full_name_stays_in_the_tooltip(app):
    assert widgets.short_device("GPU : NVIDIA GeForce RTX 4070 Ti") == "GPU : RTX 4070 Ti"
    assert widgets.short_device("GPU : NVIDIA RTX A6000") == "GPU : RTX A6000"
    assert widgets.short_device("GPU : GeForce GTX 1080") == "GPU : GTX 1080"
    assert widgets.short_device("GPU : Quadro P2000") == "GPU : Quadro P2000"
    assert widgets.short_device("GPU : NVIDIA ") == "GPU : NVIDIA "  # rien ne reste : on garde le texte d'origine
    assert widgets.short_device("Processeur (lent : aucun GPU CUDA détecté)") == "Processeur (lent : aucun GPU CUDA détecté)"
    chip = widgets.HardwareChip()
    chip.set_device("GPU : NVIDIA GeForce RTX 4070 Ti")
    assert chip._text.text() == "GPU : RTX 4070 Ti"
    assert chip.toolTip() == "GPU : NVIDIA GeForce RTX 4070 Ti"
    assert "NVIDIA GeForce RTX 4070 Ti" in chip.accessibleName()


def test_resize_watcher_reports_each_size_change(app, stage):
    seen = []
    box = QWidget(stage)
    box.resize(100, 30)
    watcher = widgets.ResizeWatcher(box, lambda: seen.append(box.width()))
    box.show()
    box.resize(140, 30)
    box.resize(160, 30)
    assert seen[-2:] == [140, 160] and watcher.parent() is box
    box.deleteLater()


def test_animate_jumps_when_motion_is_reduced(app):
    Motion.user_reduced = True
    values = []
    done = []
    assert widgets.animate(0, 1, 200, values.append, on_finished=lambda: done.append(True)) is None
    assert values == [1.0] and done == [True]


def test_ease_curve_starts_fast_and_ends_soft():
    curve = theme.ease_out()
    assert curve.valueForProgress(0.0) == pytest.approx(0.0, abs=1e-3)
    assert curve.valueForProgress(1.0) == pytest.approx(1.0, abs=1e-3)
    assert curve.valueForProgress(0.2) > 0.4  # a déjà fait près de la moitié du chemin


# ---- icônes ---------------------------------------------------------------------------------------------------------
def test_every_icon_renders(app):
    for name in icons.NAMES:
        image = icons.pixmap(name, "#ECEEF2").toImage()
        assert not image.isNull()
        assert any(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height())), name


def test_icons_used_in_code_exist():
    """Un nom d'icône mal orthographié ne doit pas attendre l'exécution pour se voir."""
    used = set()
    for name in ("studio.py", "widgets.py", "fx.py", "viewport.py", "pages.py"):
        text = (REPO / "src" / "threerex" / name).read_text(encoding="utf-8")
        used |= set(re.findall(r'(?:icon=|IconButton\(|bind_icon\([^,]+,\s*|pixmap\()"([a-z0-9-]+)"', text))
    assert used, "aucune icône repérée : l'expression régulière est à revoir"
    assert used <= set(icons.NAMES), used - set(icons.NAMES)


def test_icon_takes_the_requested_color(app):
    image = icons.pixmap("check", "#FF0000", size=24, dpr=1.0).toImage()
    solid = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
             if image.pixelColor(x, y).alpha() > 240]
    assert solid, "aucun pixel plein : le trait n'est pas dessiné"
    assert all(c.red() > 240 and c.green() < 20 and c.blue() < 20 for c in solid)
    assert image.pixelColor(0, 0).alpha() == 0  # le fond reste transparent


# ---- composants -----------------------------------------------------------------------------------------------------
def test_switch_toggles_and_exposes_name(stage):
    switch = widgets.Switch("Retirer le fond", stage)
    switch.show()
    assert switch.accessibleName() == "Retirer le fond" and not switch.isChecked()
    switch.click()
    assert switch.isChecked()
    assert switch.sizeHint().height() >= 44


def test_segmented_selection_and_api(stage):
    seg = widgets.Segmented(stage)
    for label in ("Rapide", "Standard", "Détaillé"):
        seg.addItem(f"{label} (info)", label.lower(), label=label)
    seg.show()
    seen = []
    seg.currentIndexChanged.connect(seen.append)
    assert seg.count() == 3 and seg.currentIndex() == 0
    assert seg.itemText(1) == "Standard (info)" and seg.itemData(1) == "standard"
    seg.setCurrentIndex(2)
    assert seg.currentIndex() == 2 and seen == [2]
    seg.setCurrentIndex(2)  # inchangé : pas de signal
    assert seen == [2]
    seg.clear()
    assert seg.count() == 0 and seg.currentIndex() == -1


def test_segmented_keyboard_skips_disabled_items(stage):
    from PySide6.QtTest import QTest

    seg = widgets.Segmented(stage)
    for label in ("A", "B", "C"):
        seg.addItem(label)
    seg.setItemEnabled(1, False)
    seg.show()
    seg.setFocus()
    QTest.keyClick(seg, Qt.Key.Key_Right)
    assert seg.currentIndex() == 2, "l'option désactivée est sautée"
    QTest.keyClick(seg, Qt.Key.Key_Left)
    assert seg.currentIndex() == 0
    QTest.keyClick(seg, Qt.Key.Key_End)
    assert seg.currentIndex() == 2


def test_segmented_click_ignores_disabled_item(stage):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    seg = widgets.Segmented(stage)
    seg.resize(300, 44)
    for label in ("A", "B", "C"):
        seg.addItem(label)
    seg.setItemEnabled(1, False)
    seg.show()
    QTest.mouseClick(seg, Qt.MouseButton.LeftButton, pos=QPoint(150, 22))
    assert seg.currentIndex() == 0
    QTest.mouseClick(seg, Qt.MouseButton.LeftButton, pos=QPoint(280, 22))
    assert seg.currentIndex() == 2


def test_buttons_only_take_focus_from_keyboard(app):
    assert widgets.make_button("Ok").focusPolicy() == Qt.FocusPolicy.TabFocus
    assert widgets.IconButton("house", "Accueil").focusPolicy() == Qt.FocusPolicy.TabFocus
    assert widgets.Switch("x").focusPolicy() == Qt.FocusPolicy.TabFocus
    assert widgets.Segmented().focusPolicy() == Qt.FocusPolicy.TabFocus


def test_icon_button_has_accessible_name(app):
    button = widgets.IconButton("house", "Recentrer la vue (Ctrl+0)")
    assert button.accessibleName() == "Recentrer la vue (Ctrl+0)"
    assert button.toolTip().startswith("Recentrer")


def test_set_kind_changes_role_and_is_idempotent(app):
    button = widgets.make_button("Générer", kind="primary", icon="wand-sparkles")
    widgets.set_kind(button, None)
    assert (button.property("kind") or "") == ""
    widgets.set_kind(button, "primary")
    assert button.property("kind") == "primary"


def test_dropzone_states(app):
    from PIL import Image

    zone = widgets.DropZone()
    zone.show()
    assert not zone.has_image() and zone.pixmap() is None
    zone.set_image(Image.new("RGBA", (40, 30), (200, 60, 40, 255)))
    assert zone.has_image() and zone.pixmap() is not None and not zone.has_prepared()
    zone.set_prepared(Image.new("RGB", (40, 30), (120, 120, 120)))
    assert zone.shows_prepared()
    zone.set_prepared(None)
    assert not zone.has_prepared() and zone.view.currentIndex() == 0
    zone.set_image(None)
    assert not zone.has_image()
    zone.set_dragging(True)
    assert "Relâche" in zone.title.text()
    zone.set_dragging(False)
    assert "Dépose" in zone.title.text()


def test_toast_shows_and_hides(app):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    host.resize(600, 400)
    host.show()
    toast = widgets.Toast(host)
    Motion.user_reduced = True
    toast.show_message("Enregistré : modele.glb", "success", timeout=0)
    assert toast.isVisible() and toast.message() == "Enregistré : modele.glb"
    assert 0 < toast.x() and toast.x() + toast.width() < host.width()
    toast.dismiss()
    assert not toast.isVisible()
    toast.show_message("Autre", "error", timeout=0)
    toast.hide_now()
    assert not toast.isVisible()


def test_indeterminate_bar_state(app):
    bar = widgets.IndeterminateBar()
    bar.show()
    assert not bar.isActive()
    bar.setActive(True)
    assert bar.isActive()
    bar.setActive(False)
    assert not bar.isActive() and bar.height() >= 4


def test_error_panel_content(app):
    panel = widgets.ErrorPanel()
    panel.set_error("La génération a échoué", "Mémoire GPU insuffisante.", "Réessaie.", "Traceback…", True, "Réessayer")
    panel.show()
    assert panel.btn_retry.property("kind") == "primary"
    assert not panel.btn_back.isHidden() and not panel.btn_copy.isHidden()
    panel.set_error("Titre", "Message", "", "", False, "Réessayer")
    assert panel.btn_back.isHidden() and panel.btn_copy.isHidden() and panel.hint.isHidden()


def test_settings_page_reports_choices(app):
    from threerex.pages import SettingsPage

    page = SettingsPage("version de test")
    events = []
    page.scaleChanged.connect(lambda v: events.append(("scale", v)))
    page.reduceMotionChanged.connect(lambda v: events.append(("motion", v)))
    page.effectsChanged.connect(lambda v: events.append(("effects", v)))
    page.set_state(1.0, False, True)
    assert events == [], "set_state ne doit pas émettre de signaux"
    page.seg_scale.setCurrentIndex(2)
    page.sw_motion.setChecked(True)
    page.sw_effects.setChecked(False)
    assert events == [("scale", 1.3), ("motion", True), ("effects", False)]


def test_theme_applies_with_item_views_alive(app):
    """Régression CI (PySide6 6.9) : `QListView.update()` sans argument est refusée, alors que tout widget doit être repeint."""
    from PySide6.QtWidgets import QComboBox, QListView, QTableView, QTreeView

    views = [QListView(), QTableView(), QTreeView()]
    combo = QComboBox()
    combo.addItems(["a", "b"])
    combo.showPopup()  # crée la vue interne du menu déroulant
    theme.apply_theme(app, "light", 1.0)
    theme.apply_theme(app, "dark", 1.0)
    for view in views:
        widgets.repolish(view)
    combo.hidePopup()
