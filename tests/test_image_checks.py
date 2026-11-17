"""Conseils sur l'image de départ : seuils prudents (aucune fausse alerte sur une bonne image), jamais d'exception."""

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from threerex import image_checks as ic


def figurine(size=1024, box=(0.3, 0.2, 0.7, 0.9), bg=(235, 235, 235), fill=(190, 90, 50)):
    img = Image.new("RGB", (size, size), bg)
    ImageDraw.Draw(img).ellipse(tuple(int(v * size) for v in (box[0], box[1], box[2], box[3])), fill=fill)
    return img


def test_a_good_image_gets_no_advice():
    assert ic.check_image(figurine()) == []


def test_low_contrast_but_sharp_subject_gets_no_advice():
    assert ic.check_image(figurine(bg=(225, 225, 225), fill=(200, 205, 210))) == []


def test_small_image_is_flagged_with_its_size():
    tips = ic.check_image(figurine(size=300))
    assert tips == [ic.TIP_SMALL.format(w=300, h=300)]


def test_blurry_image_is_flagged():
    assert ic.check_image(figurine().filter(ImageFilter.GaussianBlur(14))) == [ic.TIP_BLURRY]


def test_object_cut_by_the_border_is_flagged_on_a_plain_background():
    cut = figurine(box=(-0.2, 0.2, 0.6, 0.9))
    assert ic.check_image(cut) == [ic.TIP_CUT]
    assert ic.check_image(figurine(box=(0.3, 0.2, 0.7, 1.2))) == [ic.TIP_CUT]  # pieds coupés en bas


def test_a_margin_all_around_is_not_flagged():
    assert ic.check_image(figurine(box=(0.1, 0.05, 0.9, 0.95))) == []


def test_cut_cutout_is_detected_from_its_transparency():
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((300, -100, 700, 800), fill=(190, 90, 50, 255))
    assert ic.check_image(img) == [ic.TIP_CUT]
    ok = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(ok).ellipse((300, 100, 700, 900), fill=(190, 90, 50, 255))
    assert ic.check_image(ok) == []


def test_busy_background_gives_no_cut_advice_because_the_object_cannot_be_told_apart():
    rng = np.random.default_rng(1)
    blocks = Image.fromarray(rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)).resize((1024, 1024), Image.Resampling.NEAREST)
    ImageDraw.Draw(blocks).ellipse((-100, 200, 600, 900), fill=(190, 90, 50))
    assert ic.TIP_CUT not in ic.check_image(blocks)
    # fond à grandes taches (bois, herbe, nappe) : variations lentes de plusieurs dizaines de niveaux, pas assez uni pour juger
    patches = rng.integers(170, 230, (8, 8, 3), dtype=np.uint8)
    textured = Image.fromarray(patches).resize((1024, 1024), Image.Resampling.BICUBIC)
    ImageDraw.Draw(textured).ellipse((-100, 200, 600, 900), fill=(90, 60, 40))
    assert ic.TIP_CUT not in ic.check_image(textured)


def test_a_finely_grained_but_even_background_is_still_a_plain_background():
    rng = np.random.default_rng(2)
    grain = Image.fromarray(rng.integers(205, 235, (1024, 1024, 3), dtype=np.uint8))  # grain fin : uni à l'échelle de l'objet
    ImageDraw.Draw(grain).ellipse((-100, 200, 600, 900), fill=(90, 60, 40))
    assert ic.TIP_CUT in ic.check_image(grain)


def test_mild_blur_is_not_flagged_but_strong_blur_is():
    assert ic.TIP_BLURRY not in ic.check_image(figurine().filter(ImageFilter.GaussianBlur(4)))
    assert ic.TIP_BLURRY in ic.check_image(figurine().filter(ImageFilter.GaussianBlur(20)))


def test_a_soft_photo_style_gradient_object_is_not_called_blurry():
    # objet à contours nets mais ombré en dégradé, sur fond uni (rendu 3D, figurine photographiée)
    img = Image.new("RGB", (1024, 1024), (240, 240, 240))
    shade = np.linspace(80, 200, 1024, dtype=np.uint8)
    body = Image.fromarray(np.stack([np.tile(shade, (1024, 1)).T] * 3, axis=2))
    mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(mask).ellipse((300, 150, 724, 900), fill=255)
    img.paste(body, mask=mask)
    assert ic.check_image(img) == []


def test_it_is_fast_on_a_large_photo_and_never_raises():
    big = figurine(size=4000)
    started = time.perf_counter()
    assert ic.check_image(big) == []
    assert time.perf_counter() - started < 1.5
    for odd in (Image.new("RGB", (1, 1)), Image.new("L", (600, 600), 128), Image.new("P", (700, 700)), Image.new("LA", (700, 700))):
        assert isinstance(ic.check_image(odd), list)


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L"])
def test_modes_are_supported(mode):
    assert ic.check_image(figurine().convert(mode)) == []


def test_the_prompt_in_the_app_is_the_one_in_the_guide():
    guide = (Path(__file__).resolve().parents[1] / "docs" / "IMAGE_DE_DEPART.md").read_text(encoding="utf-8")
    assert ic.IMAGE_PROMPT in guide and "[DÉCRIS ICI" in ic.IMAGE_PROMPT
