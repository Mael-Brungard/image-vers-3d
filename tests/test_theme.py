"""Système de design : jetons identiques à la maquette, contrastes, feuille de style, icônes et composants."""

import colorsys
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from imagevers3d import icons, theme, widgets  # noqa: E402
from imagevers3d.theme import TOKENS, Motion, Theme, build_qss, contrast  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
MODES = ("dark", "light")
SURFACES = ("bg-app", "bg-viewport", "bg-panel", "bg-raised")


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


def test_modes_have_the_same_keys():
    assert set(TOKENS["dark"]) == set(TOKENS["light"])


@pytest.mark.parametrize("mode", MODES)
def test_no_pure_black_and_no_violet_accent(mode):
    colors = TOKENS[mode]
    assert "#000000" not in {v.upper() for v in colors.values()}
    for key in ("accent", "accent-hover", "accent-pressed", "accent-text", "accent-ui", "focus"):
        r, g, b = (int(colors[key][i : i + 2], 16) / 255 for i in (1, 3, 5))
        hue = colorsys.rgb_to_hsv(r, g, b)[0] * 360
        assert not 270 <= hue <= 330, f"{key} est violet"


# ---- contrastes -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("surface", SURFACES)
def test_text_contrast(mode, surface):
    c = TOKENS[mode]
    assert contrast(c["text"], c[surface]) >= 7, "texte principal"
    assert contrast(c["text-secondary"], c[surface]) >= 4.5
    assert contrast(c["text-muted"], c[surface]) >= 4.5
    assert contrast(c["accent-text"], c[surface]) >= 4.5, "texte d'accent"


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
        font = REPO / "src" / "imagevers3d" / "assets" / "fonts" / name
        assert font.is_file(), name
        assert QFontDatabase.addApplicationFont(str(font)) >= 0, name
    assert (REPO / "src" / "imagevers3d" / "assets" / "fonts" / "OFL.txt").is_file()
    assert (REPO / "src" / "imagevers3d" / "assets" / "LUCIDE-LICENSE.txt").is_file()


def test_fonts_are_declared_as_package_data():
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "assets/fonts/*" in pyproject


def test_system_mode_resolves(app):
    assert theme.resolve_mode("light") == "light"
    assert theme.resolve_mode("dark") == "dark"
    assert theme.resolve_mode("system") in MODES
    assert theme.resolve_mode("n'importe quoi") == "dark"


def test_apply_theme_switches_and_notifies(app):
    seen = []
    theme.bus.changed.connect(lambda: seen.append(theme.current().mode))
    theme.apply_theme(app, "light", 1.15)
    assert theme.current().mode == "light" and theme.current().scale == 1.15
    theme.apply_theme(app, "dark", 1.0)
    assert seen[-2:] == ["light", "dark"]


# ---- mouvement ------------------------------------------------------------------------------------------------------
def test_motion_can_be_reduced_by_user_or_system():
    assert Motion.enabled() and Motion.ms(200) == 200
    Motion.user_reduced = True
    assert not Motion.enabled() and Motion.ms(200) == 0
    Motion.user_reduced = False
    Motion.system_reduced = True
    assert Motion.ms(200) == 0


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
    for name in ("studio.py", "widgets.py"):
        text = (REPO / "src" / "imagevers3d" / name).read_text(encoding="utf-8")
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


def test_settings_popover_reports_choices(app):
    menu = widgets.SettingsPopover()
    events = []
    menu.themeChanged.connect(lambda v: events.append(("theme", v)))
    menu.scaleChanged.connect(lambda v: events.append(("scale", v)))
    menu.reduceMotionChanged.connect(lambda v: events.append(("motion", v)))
    menu.set_state("dark", 1.0, False)
    assert events == [], "set_state ne doit pas émettre de signaux"
    menu.seg_theme.setCurrentIndex(2)
    menu.seg_scale.setCurrentIndex(2)
    menu.sw_motion.setChecked(True)
    assert events == [("theme", "light"), ("scale", 1.3), ("motion", True)]


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
