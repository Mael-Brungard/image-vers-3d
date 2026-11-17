"""Composants d'identité et d'animation de ThreeRex : horloge, mise en page, mascotte, bulle, visualiseur, pages."""

import pytest

pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from threerex import fx, theme, viewport  # noqa: E402
from threerex.theme import Motion  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    theme.apply_theme(instance, "dark", 1.0)
    fx.Clock.require_active = False
    return instance


@pytest.fixture(autouse=True)
def motion_on():
    Motion.refresh(False, False)
    yield
    Motion.refresh(False, False)


def render(widget: QWidget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    return image


def painted(image: QImage) -> bool:
    return any(image.pixelColor(x, y).alpha() > 0 for x in range(0, image.width(), 3) for y in range(0, image.height(), 3))


# ---- horloge et réduction du mouvement ---------------------------------------------------------------------------------
def test_clock_is_static_when_effects_are_off(app):
    assert fx.Clock.t() > 0.0
    Motion.refresh(False, True)  # « Effets visuels » coupés : décor immobile, gestes toujours animés
    assert fx.Clock.t() == 0.0
    assert fx.Clock.t(ambient=False) > 0.0
    Motion.refresh(True, False)  # « Réduire les animations » : tout est immobile
    assert fx.Clock.t() == 0.0 and fx.Clock.t(ambient=False) == 0.0


def test_animated_widget_subscribes_only_while_visible(app):
    widget = fx.Animated()
    widget.resize(40, 40)
    before = fx.Clock.active_count()
    widget.show()
    assert fx.Clock.active_count() == before + 1
    widget.hide()
    assert fx.Clock.active_count() == before


# ---- mise en page ------------------------------------------------------------------------------------------------------
def _boxes(count: int, width: int = 80, height: int = 30):
    host = QWidget()
    layout = fx.FlowLayout(host, 10, 6)
    items = []
    for _ in range(count):
        label = QLabel("x", host)
        label.setFixedSize(width, height)
        layout.addWidget(label)
        items.append(label)
    return host, layout, items


def test_flow_layout_wraps_instead_of_overflowing(app):
    host, layout, items = _boxes(5)
    host.resize(200, layout.heightForWidth(200))  # 2 par ligne : 80 + 10 + 80 = 170 ≤ 200
    layout.setGeometry(host.rect())
    assert layout.heightForWidth(200) == 3 * 30 + 2 * 6
    assert all(item.geometry().right() <= 200 for item in items)
    assert items[0].geometry().y() == items[1].geometry().y() < items[2].geometry().y()


def test_flow_layout_can_center_rows(app):
    host = QWidget()
    layout = fx.FlowLayout(host, 10, 6, centered=True)
    one = QLabel("x", host)
    one.setFixedSize(100, 30)
    layout.addWidget(one)
    host.resize(300, 30)
    layout.setGeometry(host.rect())
    assert one.geometry().x() == 100  # (300 - 100) / 2


def test_flow_layout_ignores_hidden_items(app):
    host, layout, items = _boxes(3)
    items[1].hide()
    host.resize(500, 30)
    layout.setGeometry(host.rect())
    assert items[2].geometry().x() == items[0].geometry().right() + 1 + 10


# ---- puces, onglets, panneaux ------------------------------------------------------------------------------------------
def test_chip_toggles_and_fits_its_text(app):
    chip = fx.Chip("Retirer le fond")
    chip.setChecked(True)
    assert chip.isChecked()
    fm = QFontMetrics(chip.font())
    assert chip.sizeHint().width() >= fm.horizontalAdvance("Retirer le fond") + 40
    chip.resize(chip.sizeHint())
    assert painted(render(chip))


def test_tab_bar_emits_current_changed(app):
    tabs = fx.TabBar()
    for name in ("Un", "Deux", "Trois"):
        tabs.addTab(name, "box")
    seen = []
    tabs.currentChanged.connect(seen.append)
    tabs.setCurrentIndex(2)
    assert seen == [2] and tabs.currentIndex() == 2
    tabs.resize(tabs.sizeHint())
    assert painted(render(tabs))


def test_collapsible_panel_toggles_its_body(app):
    panel = fx.CollapsiblePanel("Réglages", "violet", expanded=True)
    panel.resize(320, 200)
    panel.show()
    assert panel.isExpanded() and not panel.body.isHidden()
    panel.setExpanded(False)
    assert not panel.isExpanded() and panel.body.isHidden()
    panel.setExpanded(True)
    assert not panel.body.isHidden()


# ---- identité ----------------------------------------------------------------------------------------------------------
def test_mascot_and_logo_are_painted_in_identity_colors(app):
    image = QImage(160, 160, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fx.paint_mark(p, QRectF(0, 0, 160, 160))
    p.end()
    hues = {QColor(image.pixelColor(x, y)).hue() for x in range(0, 160, 4) for y in range(0, 160, 4)
            if image.pixelColor(x, y).alpha() > 200 and QColor(image.pixelColor(x, y)).saturation() > 120}
    assert any(10 <= h <= 40 for h in hues), "pas d'orange"
    assert any(245 <= h <= 275 for h in hues), "pas de violet"


def test_logo_drops_its_tagline_when_compact(app):
    logo = fx.Logo(44)
    full = logo.width()
    logo.set_compact(True)
    assert logo.width() < full
    logo.set_compact(False)
    assert logo.width() == full


def test_robot_is_fully_painted_and_clickable(app):
    robot = fx.Robot(56)
    robot.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)  # on ne mesure que le dessin, pas le fond de la fenêtre
    robot.show()
    got = []
    robot.clicked.connect(lambda: got.append(1))
    from PySide6.QtTest import QTest

    QTest.mouseClick(robot, Qt.MouseButton.LeftButton)
    assert got == [1]
    assert max(_edge_alphas(render(robot))) == 0, "le robot est coupé par le bord de son cadre"


def _edge_alphas(image: QImage) -> list[int]:
    w, h = image.width(), image.height()
    return [image.pixelColor(x, y).alpha() for x in range(w) for y in (0, h - 1)] + [image.pixelColor(x, y).alpha() for y in range(h) for x in (0, w - 1)]


@pytest.mark.parametrize("size", [40, 56, 73, 96])  # 56 px × échelle de texte (de 90 % à 130 %), puis plus grand par sécurité
@pytest.mark.parametrize("bob", [-fx.Robot.BOB, 0.0, fx.Robot.BOB])
@pytest.mark.parametrize("blink", [0.0, 1.0])
def test_robot_never_touches_its_frame_at_any_phase(app, size, bob, blink):
    """Le balancement et le clignement sont animés : on vérifie leurs positions extrêmes, pas seulement l'image du moment."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    fx.paint_robot(p, QRectF(0, 0, size, size), blink=blink, bob=bob, glow=1.0)
    p.end()
    assert max(_edge_alphas(image)) == 0, (size, bob, blink)


# ---- bulle de l'assistant ----------------------------------------------------------------------------------------------
def test_bubble_reports_elision(app):
    bubble = fx.Bubble()
    bubble.resize(300, bubble.sizeHint().height())
    bubble.set_text("Image prête.")
    assert not bubble.is_elided()
    bubble.set_text("Un texte beaucoup trop long pour tenir sur deux lignes dans une bulle aussi étroite, " * 3)
    assert bubble.is_elided()
    assert bubble.toolTip().startswith("Un texte")  # le texte complet reste accessible


def test_wrap_elide_never_exceeds_the_line_count(app):
    fm = QFontMetrics(QLabel().font())
    lines = fx.wrap_elide("mot " * 80, fm, 160, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert fx.wrap_elide("court", fm, 160, 2) == ["court"]


# ---- reconstruction et particules --------------------------------------------------------------------------------------
def test_reconstruction_view_is_honest_and_paints(app):
    view = fx.ReconstructionView()
    view.resize(300, 300)
    assert not view.has_source()
    view.set_source(Image.new("RGB", (64, 64), (200, 90, 50)))
    assert view.has_source()
    view.show()
    assert painted(render(view))
    view.set_source(None)
    assert not view.has_source()


def test_particles_pause_during_gestures(app):
    field = fx.ParticleField()
    field.resize(200, 200)
    assert not field.paused()
    field.pause_for(0.5)
    assert field.paused()


# ---- gestes du visualiseur ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("mode", "buttons", "modifiers", "expected"),
    [
        ("rotate", Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, "orbit"),
        ("pan", Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, "pan"),
        ("zoom", Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, "zoom"),
        ("rotate", Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, "pan"),
        ("rotate", Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, "pan"),
        ("rotate", Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, "zoom"),
        ("rotate", Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, None),
        ("rotate", Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, None),
    ],
)
def test_drag_action_maps_buttons_to_gestures(mode, buttons, modifiers, expected):
    assert viewport.drag_action(mode, buttons, modifiers) == expected


def test_viewport_frame_pages_and_modes(app):
    frame = viewport.ViewportFrame()
    frame.resize(900, 600)
    frame.show()
    assert frame.page_name() == frame.EMPTY
    for page in (frame.BUSY, frame.ERROR, frame.RESULT, frame.EMPTY):
        frame.show_page(page)
        assert frame.page_name() == page
    frame.show_page(frame.RESULT)
    assert frame.toolbar.isVisible() and frame.modebar.isVisible()
    frame.show_page(frame.EMPTY)
    assert not frame.toolbar.isVisible() and not frame.modebar.isVisible()
    for mode in viewport.MODES:
        frame.set_mode(mode)
        assert frame.mode() == mode and frame.mode_buttons[mode].isChecked()


def test_viewport_overlays_never_overlap_when_narrow(app):
    frame = viewport.ViewportFrame()
    frame.resize(620, 440)
    frame.show_page(frame.RESULT)
    frame.show()
    frame.show_variants(True)
    frame.set_info("variante 1/4 · 412 380 sommets · TRELLIS.2 · 1024")
    boxes = [w.geometry() for w in (frame.toolbar, frame.modebar, frame.variant_bar, frame.info) if w.isVisible()]
    for i, a in enumerate(boxes):
        assert QRectF(0, 0, frame.width(), frame.height()).contains(QRectF(a)), a
        for b in boxes[i + 1:]:
            inter = a.intersected(b)
            assert inter.width() <= 2 or inter.height() <= 2, (a, b)
    assert frame.info.text().startswith("variante 1/4")  # l'essentiel reste, la fin est retirée


def test_fullscreen_button_changes_its_label(app):
    frame = viewport.ViewportFrame()
    frame.set_fullscreen_state(True)
    assert "Quitter" in frame.btn_full.accessibleName()
    frame.set_fullscreen_state(False)
    assert frame.btn_full.accessibleName() == "Plein écran"


def test_assistant_tips_fit_in_two_lines_at_the_narrowest_footer(app):
    """Chaque astuce du robot doit tenir dans sa bulle à la largeur la plus faible prévue (fenêtre 1000 px, texte 130 %)."""
    from threerex import studio

    bubble = fx.Bubble()
    bubble.resize(theme.current().px(300), bubble.sizeHint().height())
    for tip in (*studio.TIPS, studio.STL_OPEN_HINT):
        bubble.set_text(tip)
        assert not bubble.is_elided(), tip
    assert QSize(1, 1).isValid()
