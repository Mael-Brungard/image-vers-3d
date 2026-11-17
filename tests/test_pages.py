"""Pages « Mes créations » et « Paramètres », durées et pastilles honnêtes de la fenêtre principale."""

import pytest

pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from threerex import fx, studio, theme  # noqa: E402
from threerex.creations import CreationStore  # noqa: E402
from threerex.pages import CreationsPage, SettingsPage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    theme.apply_theme(instance, "dark", 1.0)
    fx.Clock.require_active = False
    return instance


def test_creations_page_empty_then_filled_and_remove_keeps_the_file(app, tmp_path):
    store = CreationStore(tmp_path / "data")
    page = CreationsPage(store)
    page.resize(900, 600)
    page.show()
    assert not page.empty.isHidden() and page.scroll.isHidden() and page.count.text() == ""
    model = tmp_path / "vase.glb"
    model.write_bytes(b"glb" * 1000)
    store.add(model, engine="TripoSR", info="256 · 642 sommets", thumbnail=Image.new("RGB", (32, 32), (200, 90, 50)))
    page.refresh()
    assert page.empty.isHidden() and not page.scroll.isHidden()
    assert len(page.cards) == 1 and page.count.text() == "1 modèle"
    seen = []
    page.openRequested.connect(seen.append)
    page.cards[0].btn_open.click()
    assert seen == [str(model)]
    page.cards[0].btn_remove.click()
    assert not page.cards and model.exists(), "retirer une carte ne doit jamais supprimer le fichier"


def test_creation_card_flags_a_missing_file(app, tmp_path):
    store = CreationStore(tmp_path / "data")
    gone = tmp_path / "disparu.glb"
    gone.write_bytes(b"x")
    store.add(gone, engine="TripoSR", info="", thumbnail=None)
    gone.unlink()
    page = CreationsPage(store)
    card = page.cards[0]
    assert card.missing and not card.btn_open.isEnabled()


def test_creation_cards_share_the_same_height(app, tmp_path):
    store = CreationStore(tmp_path / "data")
    for name in ("a.glb", "b.glb", "c.glb"):
        f = tmp_path / name
        f.write_bytes(b"x")
        store.add(f, engine="TripoSR", info="1024", thumbnail=None)
    (tmp_path / "b.glb").unlink()  # sa carte porte un avertissement en plus
    page = CreationsPage(store)
    assert len({card.height() for card in page.cards}) == 1


def test_settings_page_reflects_state_without_signals(app):
    page = SettingsPage("version test")
    page.set_device("GPU : NVIDIA GeForce RTX 4070 Ti")
    assert "RTX 4070 Ti" in page.device.text()
    page.set_state(1.15, True, False)
    assert page.sw_motion.isChecked() and not page.sw_effects.isChecked()
    assert page.seg_scale.currentIndex() == 1


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0 s"), (42.4, "42 s"), (59.6, "1 min 00 s"), (134, "2 min 14 s"), (3900, "1 h 05 min")],
)
def test_format_duration_reads_naturally(seconds, text):
    assert studio.format_duration(seconds) == text


def test_engine_badges_are_labels_not_promises():
    """Les pastilles à côté du moteur décrivent le choix ; jamais une durée ou un gain chiffré inventé."""
    assert set(studio.ENGINE_BADGES) == set(studio.ENGINE_NAMES)
    for text, tone in studio.ENGINE_BADGES.values():
        assert tone in ("orange", "violet")
        assert not any(ch.isdigit() for ch in text), text
    assert studio.ENGINE_BADGES["trellis"][0] == "Recommandé"
