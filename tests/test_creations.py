"""Liste « Mes créations » : ajout, ordre, vignettes, remplacement, retrait, fichier abîmé."""

import json
import time

from PIL import Image

from threerex import creations
from threerex.creations import CreationStore, format_size, format_when


def make_file(folder, name="tasse.glb", size=2048):
    path = folder / name
    path.write_bytes(b"x" * size)
    return path


def test_add_and_load_most_recent_first(tmp_path):
    store = CreationStore(tmp_path / "c")
    assert store.load() == []
    first = store.add(make_file(tmp_path, "a.glb"), engine="TripoSR", info="10 sommets")
    time.sleep(0.01)
    second = store.add(make_file(tmp_path, "b.obj", 5000), engine="TRELLIS.2")
    items = store.load()
    assert [c.name for c in items] == ["b.obj", "a.glb"]
    assert items[0].format == "obj" and items[0].size == 5000 and items[1].info == "10 sommets"
    assert first.id != second.id and items[0].exists()


def test_same_file_saved_twice_keeps_one_entry(tmp_path):
    store = CreationStore(tmp_path / "c")
    path = make_file(tmp_path)
    store.add(path, engine="TripoSR")
    store.add(path, engine="TRELLIS.2")
    items = store.load()
    assert len(items) == 1 and items[0].engine == "TRELLIS.2"


def test_thumbnail_is_saved_small_and_removed_with_the_entry(tmp_path):
    store = CreationStore(tmp_path / "c")
    created = store.add(make_file(tmp_path), thumbnail=Image.new("RGBA", (1000, 800), (200, 60, 40, 255)))
    thumb = store.thumb_path(created)
    assert thumb is not None and thumb.is_file()
    with Image.open(thumb) as img:
        assert max(img.size) <= creations.THUMB_SIZE
    assert store.remove(created.id)
    assert not thumb.exists() and store.load() == []
    assert not store.remove("inconnu")


def test_remove_never_deletes_the_model_file(tmp_path):
    store = CreationStore(tmp_path / "c")
    path = make_file(tmp_path)
    created = store.add(path)
    store.remove(created.id)
    assert path.is_file()


def test_missing_model_is_reported(tmp_path):
    store = CreationStore(tmp_path / "c")
    path = make_file(tmp_path)
    store.add(path)
    path.unlink()
    assert not store.load()[0].exists()


def test_limit_drops_oldest_and_their_thumbnails(tmp_path):
    store = CreationStore(tmp_path / "c", limit=3)
    ids = []
    for k in range(5):
        ids.append(store.add(make_file(tmp_path, f"m{k}.glb"), thumbnail=Image.new("RGB", (20, 20))).id)
        time.sleep(0.005)
    items = store.load()
    assert [c.name for c in items] == ["m4.glb", "m3.glb", "m2.glb"]
    assert sorted(p.name for p in (tmp_path / "c").glob("*.jpg")) == sorted(f"{i}.jpg" for i in ids[2:])


def test_damaged_file_or_entries_do_not_break_loading(tmp_path):
    store = CreationStore(tmp_path / "c")
    (tmp_path / "c").mkdir()
    store.file.write_text("pas du json", encoding="utf-8")
    assert store.load() == []
    store.file.write_text(json.dumps([{"id": "a"}, 3, {"id": "b", "path": "/x/y.glb", "inconnu": 1}]), encoding="utf-8")
    assert [c.id for c in store.load()] == ["b"]
    assert store.add(make_file(tmp_path)) is not None  # on peut repartir d'un fichier abîmé


def test_add_never_raises_when_the_disk_refuses(tmp_path):
    blocker = tmp_path / "pas_un_dossier"
    blocker.write_text("x")
    store = CreationStore(blocker / "c")
    assert store.add(make_file(tmp_path)) is None


def test_formats():
    assert format_size(500) == "500 o" and format_size(812_000) == "812 Ko" and format_size(4_200_000) == "4,2 Mo"
    now = time.mktime((2026, 11, 17, 15, 0, 0, 0, 0, -1))
    assert format_when(now - 3600, now).startswith("Aujourd'hui, ")
    assert format_when(now - 86400, now).startswith("Hier, ")
    assert format_when(now - 10 * 86400, now) == "07/11/2026"
