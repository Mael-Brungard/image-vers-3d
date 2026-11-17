"""Redessine l'icône de l'application (src/threerex/assets/icon.png et icon.ico) à partir de la mascotte vectorielle.

    python scripts/make_icon.py

La mascotte est dessinée par `threerex.fx.paint_mark` : une seule source pour l'interface, le logo et l'icône.
Une carte arrondie sombre, un halo violet et la tête de T-Rex orange ; les petites tailles ont un trait un peu plus épais.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from threerex import fx, theme  # noqa: E402

ASSETS = REPO / "src" / "threerex" / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    t = theme.current()
    card = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    radius = size * 0.22
    base = QLinearGradient(QPointF(0, 0), QPointF(0, size))
    base.setColorAt(0.0, QColor("#241C4A"))
    base.setColorAt(1.0, t.color("bg-deep"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(base))
    p.drawRoundedRect(card, radius, radius)
    glow = QRadialGradient(QPointF(size * 0.5, size * 0.55), size * 0.6)
    glow.setColorAt(0.0, fx.with_alpha(t.color("violet"), 0.55))
    glow.setColorAt(1.0, fx.with_alpha(t.color("violet"), 0.0))
    p.setBrush(QBrush(glow))
    p.drawRoundedRect(card, radius, radius)
    p.setPen(fx.with_alpha(t.color("violet-hover"), 0.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(card, radius, radius)
    fx.paint_mark(p, QRectF(size * 0.14, size * 0.16, size * 0.72, size * 0.72), glow=0.0 if size < 48 else 0.8)
    p.end()
    return image


def main() -> None:
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app, "dark", 1.0)
    from PIL import Image

    def to_pil(img: QImage) -> "Image.Image":
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        return Image.frombuffer("RGBA", (img.width(), img.height()), bytes(img.constBits()), "raw", "RGBA", img.bytesPerLine(), 1)

    big = to_pil(render(1024)).resize((512, 512), Image.LANCZOS)
    big.save(ASSETS / "icon.png")
    frames = [to_pil(render(s * 4)).resize((s, s), Image.LANCZOS) for s in SIZES]  # sur-échantillonnage : traits nets aux petites tailles
    frames[-1].save(ASSETS / "icon.ico", format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print("icônes écrites dans", ASSETS)


if __name__ == "__main__":
    main()
