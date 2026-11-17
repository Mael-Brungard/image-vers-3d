"""
print_dialog.py - Petite fenêtre « Impression 3D » : hauteur de la figurine et aplatissement du dessous, avant l'export STL.

Elle s'ouvre quand on enregistre en STL. Aucun calcul ici : elle ne fait que recueillir deux réglages et annoncer la taille
au sol que donnera la hauteur choisie (à partir des proportions réelles du modèle).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from . import fx, theme
from .printing import HEIGHT_RANGE_MM, PrintOptions
from .widgets import make_button, text_label

INTRO = ("Le fichier STL est réparé (trous fermés, petits morceaux flottants retirés), mis à l'échelle et posé à plat. "
         "Il ne contient pas de couleurs : tu peindras la figurine, ou tu garderas le GLB pour une imprimante multicolore.")
FLATTEN_HINT = ("Coupe au plus 1,5 % de la hauteur pour que la figurine tienne à plat sur le plateau. "
                "Sans effet si le dessous est déjà plat, comme un socle.")


class PrintDialog(QDialog):
    """`ratios` : (largeur / hauteur, profondeur / hauteur) du modèle debout, ou None si on ne les connaît pas."""

    def __init__(self, parent: QWidget | None, ratios: tuple[float, float] | None, options: PrintOptions) -> None:
        super().__init__(parent)
        t = theme.current()
        self._ratios = ratios
        self.setObjectName("printDialog")
        self.setWindowTitle("Impression 3D")
        self.setModal(True)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(t.px(24), t.px(22), t.px(24), t.px(20))
        root.setSpacing(t.px(14))
        title = QLabel("Préparer pour l'impression")
        title.setObjectName("h2")
        root.addWidget(title)
        root.addWidget(text_label(INTRO, role="secondary", wrap=True))

        row = QHBoxLayout()
        row.setSpacing(t.px(12))
        row.addWidget(text_label("Hauteur de la figurine", role="label"), 1)
        self.spn_height = QSpinBox()
        self.spn_height.setRange(*HEIGHT_RANGE_MM)
        self.spn_height.setSuffix(" mm")
        self.spn_height.setValue(min(max(int(options.height_mm), HEIGHT_RANGE_MM[0]), HEIGHT_RANGE_MM[1]))
        self.spn_height.setFixedWidth(t.px(124))
        self.spn_height.lineEdit().setTextMargins(t.px(12), 0, 0, 0)
        self.spn_height.setAccessibleName("Hauteur de la figurine, en millimètres")
        self.spn_height.valueChanged.connect(self._update_size)
        row.addWidget(self.spn_height)
        root.addLayout(row)
        self.lbl_size = text_label("", role="muted", wrap=True)
        root.addWidget(self.lbl_size)

        self.chk_flat = fx.Chip("Aplatir le dessous si besoin")
        self.chk_flat.setChecked(options.flatten)
        self.chk_flat.setAccessibleDescription(FLATTEN_HINT)
        root.addWidget(self.chk_flat, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(text_label(FLATTEN_HINT, role="muted", wrap=True))

        buttons = QHBoxLayout()
        buttons.setSpacing(t.px(10))
        buttons.addStretch(1)
        self.btn_cancel = make_button("Annuler", name="btn_print_cancel")
        self.btn_ok = make_button("Continuer", kind="primary", name="btn_print_ok")
        self.btn_ok.setDefault(True)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_ok)
        root.addSpacing(t.px(4))
        root.addLayout(buttons)

        self._width = t.px(480)
        self.setFixedWidth(self._width)
        self._update_size()

    def values(self) -> PrintOptions:
        return PrintOptions(height_mm=self.spn_height.value(), flatten=self.chk_flat.isChecked())

    def _update_size(self, *_args) -> None:
        height = self.spn_height.value()
        if self._ratios is None:
            self.lbl_size.setText(f"Hauteur : {height} mm.")
        else:
            wide, deep = self._ratios
            self.lbl_size.setText(f"Environ {round(height * wide)} × {round(height * deep)} mm au sol, pour {height} mm de haut.")
        self._fit_height()

    def _fit_height(self) -> None:
        """Hauteur exacte pour la largeur fixe : Qt ne la calcule pas seul quand des textes passent à la ligne."""
        layout = self.layout()
        layout.activate()
        self.setFixedHeight(layout.totalHeightForWidth(self._width))
