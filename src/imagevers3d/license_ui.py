"""
license_ui.py - écran « Licence » : activation, essai gratuit, gestion de l'ordinateur activé.

Mêmes règles que le reste de l'interface : une seule action principale par vue, aucune fenêtre modale (les erreurs
s'affichent dans la page), tout se fait au clavier, textes qui se replient, mouvement réduit respecté.
Les appels réseau (activation, essai) tournent dans un fil à part : l'interface ne se fige jamais.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import license as licensing
from . import theme
from ._licproto import TRIAL_DAYS, LicenseError, normalize_key
from .widgets import HeroMark, IndeterminateBar, make_button, repolish, set_kind, text_label


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def account_url() -> str:
    base = licensing.server_url()
    return base + "/" if base else ""


def buy_url() -> str:
    return licensing.buy_url()


class _JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str, str)  # code, message


class _Job(QRunnable):
    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _JobSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except LicenseError as exc:
            self.signals.failed.emit(exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - jamais de fil qui meurt en silence
            self.signals.failed.emit("error", f"Une erreur inattendue s'est produite ({type(exc).__name__}).")
        else:
            self.signals.done.emit(result)


class _Card(QFrame):
    """Carte à largeur fixe dont les textes se replient : Qt n'applique pas seul « hauteur selon la largeur » à un widget
    centré dans une mise en page, et le contenu se chevaucherait. On fixe donc la hauteur minimale à la hauteur voulue."""

    def event(self, event) -> bool:  # noqa: N802
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Resize, QEvent.Type.Show):
            layout = self.layout()
            if layout is not None and self.width() > 0:
                needed = layout.totalHeightForWidth(self.width())
                if needed > 0 and self.minimumHeight() != needed:
                    self.setMinimumHeight(needed)
        return result


class LicenseChip(QPushButton):
    """Pastille de la barre supérieure pendant l'essai : « Essai : 5 j ». Un clic ouvre l'écran Licence."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("btn_trial")
        self.setProperty("btnsize", "sm")
        self.setProperty("kind", "chip")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from . import icons

        icons.bind_icon(self, "clock", "accent-text")
        self.setVisible(False)

    def set_status(self, status: licensing.LicenseStatus) -> None:
        trial = status.state == "trial"
        self.setVisible(trial)
        if trial:
            days = status.days_left or 1
            self.setText(f"Essai : {days} j")
            self.setToolTip(f"{status.message}\nClique pour activer ta licence.")
            self.setAccessibleName(f"{status.message} Ouvrir l'écran Licence.")


class LicenseGate(QWidget):
    """Page pleine fenêtre. `blocking` : sans licence valable, pas de bouton Fermer ; sinon (gestion) on peut revenir."""

    statusChanged = Signal(object)  # LicenseStatus
    closeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transparent")
        self._status: licensing.LicenseStatus | None = None
        self._closable = False
        self._busy = False
        self._confirm_deactivate = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        self.card = _Card()
        self.card.setObjectName("gateCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(36, 32, 36, 28)
        v.setSpacing(10)
        self.mark = HeroMark(88)
        v.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addSpacing(6)
        self.title = text_label("", name="title", wrap=True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body = text_label("", role="secondary", wrap=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.title)
        v.addWidget(self.body)
        v.addSpacing(6)

        # --- saisie de la clé
        self.key_section = QWidget()
        self.key_section.setObjectName("transparent")
        kv = QVBoxLayout(self.key_section)
        kv.setContentsMargins(0, 0, 0, 0)
        kv.setSpacing(8)
        kv.addWidget(text_label("Clé de licence", role="label"))
        self.key_input = QLineEdit()
        self.key_input.setObjectName("key_input")
        self.key_input.setPlaceholderText("I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        self.key_input.setAccessibleName("Clé de licence")
        self.key_input.setAccessibleDescription("Reçue par e-mail après l'achat. Elle commence par I3D.")
        self.key_input.setMaxLength(64)
        self.key_input.setClearButtonEnabled(False)
        self.key_input.returnPressed.connect(self._on_activate)
        self.key_input.textChanged.connect(self._on_key_changed)
        kv.addWidget(self.key_input)
        self.btn_activate = make_button("Activer ma licence", kind="primary", icon="key-round", name="btn_activate", large=True)
        self.btn_activate.clicked.connect(self._on_activate)
        kv.addWidget(self.btn_activate)
        self.key_hint = text_label(
            "Tu la trouves dans l'e-mail reçu après l'achat. L'activation se fait une seule fois : ensuite le logiciel "
            "fonctionne sans connexion Internet.",
            role="muted",
            wrap=True,
        )
        kv.addWidget(self.key_hint)
        v.addWidget(self.key_section)

        # --- message en ligne (erreur ou confirmation) et progression
        self.message = text_label("", role="secondary", wrap=True)
        self.message.setObjectName("gate_message")
        self.message.setVisible(False)
        v.addWidget(self.message)
        self.progress = IndeterminateBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)

        # --- essai
        self.btn_trial = make_button(f"Essayer {TRIAL_DAYS} jours gratuitement", icon="clock", name="btn_start_trial", large=True)
        self.btn_trial.clicked.connect(self._on_trial)
        v.addWidget(self.btn_trial)

        # --- gestion de l'ordinateur activé
        self.btn_deactivate = make_button("Désactiver cet ordinateur", kind="ghost", name="btn_deactivate", icon_role="text-secondary")
        self.btn_deactivate.clicked.connect(self._on_deactivate)
        v.addWidget(self.btn_deactivate)
        self.deactivate_hint = text_label(
            "La licence sera retirée de cet ordinateur pour pouvoir l'activer ailleurs (quota de libérations par an). "
            "Clique encore pour confirmer.",
            role="muted",
            wrap=True,
        )
        self.deactivate_hint.setVisible(False)
        v.addWidget(self.deactivate_hint)

        # --- liens et fermeture
        links = QHBoxLayout()
        links.setSpacing(8)
        self.btn_buy = make_button("Acheter une licence", kind="ghost", icon="external-link", name="btn_buy", icon_role="text-secondary")
        self.btn_account = make_button("Mon espace client", kind="ghost", icon="external-link", name="btn_account", icon_role="text-secondary")
        self.btn_close = make_button("Fermer", kind="ghost", name="btn_close_gate", icon_role="text-secondary")
        self.btn_buy.clicked.connect(lambda: open_url(buy_url()))
        self.btn_account.clicked.connect(lambda: open_url(account_url()))
        self.btn_close.clicked.connect(self.closeRequested)
        for b in (self.btn_buy, self.btn_account):
            links.addWidget(b)
        links.addStretch(1)
        links.addWidget(self.btn_close)
        v.addLayout(links)
        self.privacy = text_label(
            "À l'activation, le serveur de licence reçoit une empreinte anonyme et le nom de cet ordinateur, une seule fois. "
            "Jamais tes images, tes modèles ou tes fichiers.",
            role="muted",
            wrap=True,
        )
        v.addWidget(self.privacy)

        self._apply_width()
        theme.bus.changed.connect(self._apply_width)

    def _apply_width(self) -> None:
        self.card.setFixedWidth(theme.current().px(540))

    # ---- affichage -----------------------------------------------------------
    def show_status(self, status: licensing.LicenseStatus, closable: bool) -> None:
        self._status = status
        self._closable = closable
        self._confirm_deactivate = False
        state = status.state
        titles = {
            "none": ("Bienvenue dans Image vers 3D", f"Essaie gratuitement pendant {TRIAL_DAYS} jours, ou active ta licence si tu l'as déjà achetée."),
            "trial": (status.message, "Tout est débloqué pendant l'essai. Tu peux activer ta licence dès maintenant : ton travail en cours est conservé."),
            "trial_expired": ("Ton essai gratuit est terminé", "Pour continuer, active ta licence. Tes réglages et tes fichiers sont conservés."),
            "licensed": ("Licence active", "Cet ordinateur est activé. Le logiciel fonctionne sans connexion Internet."),
            "clock": ("L'heure de l'ordinateur a changé", status.message),
            "invalid": ("Licence non valable sur cet ordinateur", status.message),
        }
        title, body = titles.get(state, titles["none"])
        self.title.setText(title)
        self.body.setText(body)
        licensed = state == "licensed"
        self.key_section.setVisible(not licensed)
        self.btn_trial.setVisible(state == "none")
        set_kind(self.btn_trial, None)
        self.btn_deactivate.setVisible(licensed and status.license_id is not None)
        self.btn_deactivate.setText("Désactiver cet ordinateur")
        self.deactivate_hint.setVisible(False)
        self.btn_buy.setVisible(not licensed and bool(buy_url()))
        self.btn_account.setVisible(bool(account_url()))
        self.btn_close.setVisible(closable)
        self.btn_close.setText("Revenir au logiciel" if licensed else "Fermer")
        set_kind(self.btn_close, "primary" if licensed else "ghost")  # une seule action principale par vue
        self.set_message("")
        self.title.setAccessibleName(title)
        self._set_busy(False)
        repolish(self.btn_trial)

    def set_message(self, text: str, error: bool = False) -> None:
        self.message.setText(text)
        self.message.setProperty("role", "danger" if error else "secondary")
        repolish(self.message)
        self.message.setVisible(bool(text))
        self.message.setAccessibleName(("Erreur : " if error else "") + text)
        self.key_input.setProperty("invalid", "true" if error and self.key_section.isVisible() else "false")
        repolish(self.key_input)

    def focus_first(self) -> None:
        if self.key_section.isVisible():
            self.key_input.setFocus(Qt.FocusReason.TabFocusReason)
        elif self.btn_close.isVisible():
            self.btn_close.setFocus(Qt.FocusReason.TabFocusReason)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        for w in (self.btn_activate, self.btn_trial, self.btn_deactivate, self.key_input, self.btn_buy, self.btn_account):
            w.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)

    def _on_key_changed(self, _text: str) -> None:
        if self.key_input.property("invalid") == "true":
            self.key_input.setProperty("invalid", "false")
            repolish(self.key_input)

    # ---- actions -------------------------------------------------------------
    def _run(self, fn, done, busy_text: str) -> None:
        if self._busy:
            return
        self.set_message(busy_text)
        self._set_busy(True)
        job = _Job(fn)
        job.signals.done.connect(done)
        job.signals.failed.connect(self._failed)
        self._pool.start(job)

    def _on_activate(self) -> None:
        text = self.key_input.text()
        if normalize_key(text) is None:
            self.set_message("Cette clé n'a pas le bon format. Elle ressemble à I3D-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX : copie-colle-la depuis l'e-mail.", error=True)
            self.key_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        manager = licensing.get_manager()
        self._run(lambda: manager.activate(text), self._activated, "Activation en cours…")

    def _on_trial(self) -> None:
        manager = licensing.get_manager()
        self._run(manager.start_trial, self._trial_started, "Démarrage de l'essai…")

    def _on_deactivate(self) -> None:
        if not self._confirm_deactivate:
            self._confirm_deactivate = True
            self.btn_deactivate.setText("Confirmer : désactiver cet ordinateur")
            self.deactivate_hint.setVisible(True)
            return
        manager = licensing.get_manager()
        self._run(manager.deactivate, self._deactivated, "Désactivation en cours…")

    def _activated(self, status: licensing.LicenseStatus) -> None:
        self._set_busy(False)
        self.key_input.clear()
        self.statusChanged.emit(status)

    def _trial_started(self, status: licensing.LicenseStatus) -> None:
        self._set_busy(False)
        self.statusChanged.emit(status)

    def _deactivated(self, status: licensing.LicenseStatus) -> None:
        self._set_busy(False)
        self.statusChanged.emit(status)

    def _failed(self, code: str, message: str) -> None:
        self._set_busy(False)
        self._confirm_deactivate = False
        self.btn_deactivate.setText("Désactiver cet ordinateur")
        self.deactivate_hint.setVisible(False)
        self.set_message(message, error=True)


__all__ = ["LicenseChip", "LicenseGate", "open_url"]
