from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.i18n import UI_TEXTS
from .map_widget import OfflineMapWidget


class ConnectionInterfaceDialog(QDialog):
    def __init__(
        self,
        current_mode: str,
        profiles: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connexion reseau")
        self.resize(400, 210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        intro = QLabel("Choisir l'interface de connexion et renseigner le point d'acces.")
        intro.setWordWrap(True)
        intro.setObjectName("pageSubtitle")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["UDP", "TCP", "SERIAL"])
        self.mode_combo.setCurrentText(current_mode if current_mode in profiles else "UDP")
        form.addRow("Interface", self.mode_combo)

        self.endpoint_input = QLineEdit()
        self.endpoint_input.setMinimumWidth(230)
        form.addRow("Adresse", self.endpoint_input)
        layout.addLayout(form)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("metricHint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        language = getattr(parent, "current_language", "en")
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText(UI_TEXTS.get(language, UI_TEXTS["en"])["cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._profiles = profiles
        self.mode_combo.currentTextChanged.connect(self._update_endpoint_hint)
        self._update_endpoint_hint(self.mode_combo.currentText())

    def _update_endpoint_hint(self, mode: str) -> None:
        endpoint = self._profiles.get(mode, "")
        self.endpoint_input.setText(endpoint)
        if mode == "SERIAL":
            self.endpoint_input.setPlaceholderText("COM3@115200")
            self.hint_label.setText("Format serial: COM3@115200")
        else:
            self.endpoint_input.setPlaceholderText("host:port")
            self.hint_label.setText("Format reseau: host:port")

    def connection_profile(self) -> tuple[str, str]:
        return self.mode_combo.currentText(), self.endpoint_input.text().strip()


class ActionConfirmationDialog(QDialog):
    """Modern tactical confirmation dialog for critical drone flight actions."""

    def __init__(
        self,
        title: str,
        message: str,
        level: str = "warning",
        confirm_text: str = "CONFIRM",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setMaximumWidth(520)

        color_map = {
            "info": ("#00d4ff", "#07263b", "[INFO]"),
            "warning": ("#f59e0b", "#3b2607", "[WARNING]"),
            "danger": ("#ef4444", "#3b0c0c", "[CRITICAL DANGER]"),
        }
        accent, bg_glow, badge_text = color_map.get(level, color_map["warning"])

        self.setStyleSheet(f"""
            QDialog {{
                background-color: #0b111c;
                border: 2px solid {accent};
                border-radius: 12px;
            }}
            QLabel#badgeLabel {{
                color: {accent};
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.5px;
                background-color: {bg_glow};
                border: 1px solid {accent};
                border-radius: 4px;
                padding: 3px 8px;
            }}
            QLabel#titleLabel {{
                color: #ffffff;
                font-size: 16px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }}
            QLabel#messageLabel {{
                color: #c9d8ec;
                font-size: 13px;
                line-height: 1.4;
            }}
            QPushButton#confirmButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent}, stop:1 #1e293b);
                color: #ffffff;
                font-size: 12px;
                font-weight: 800;
                padding: 9px 20px;
                border-radius: 6px;
                border: 1px solid {accent};
            }}
            QPushButton#confirmButton:hover {{
                background: {accent};
                color: #000000;
            }}
            QPushButton#cancelButton {{
                background-color: #1a2333;
                color: #8fa0b5;
                font-size: 12px;
                font-weight: 600;
                padding: 9px 18px;
                border-radius: 6px;
                border: 1px solid #2d3b50;
            }}
            QPushButton#cancelButton:hover {{
                background-color: #27354a;
                color: #ffffff;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel(badge_text)
        badge.setObjectName("badgeLabel")
        header.addWidget(badge)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("titleLabel")
        header.addWidget(title_lbl, 1)
        layout.addLayout(header)

        msg_lbl = QLabel(message)
        msg_lbl.setObjectName("messageLabel")
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)

        cancel_btn = QPushButton("Annuler" if getattr(parent, "current_language", "en") == "fr" else "Cancel")
        cancel_btn.setObjectName("cancelButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setObjectName("confirmButton")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def confirm(
        parent: QWidget | None,
        title: str,
        message: str,
        level: str = "warning",
        confirm_text: str = "CONFIRMER",
    ) -> bool:
        dlg = ActionConfirmationDialog(title, message, level=level, confirm_text=confirm_text, parent=parent)
        return dlg.exec() == QDialog.Accepted


class TakeoffAltitudeDialog(QDialog):
    """Dialog to safely set target altitude before initiating automated takeoff."""

    def __init__(self, default_alt: float = 5.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        is_fr = getattr(parent, "current_language", "en") == "fr"
        self.setWindowTitle("Décollage assisté" if is_fr else "Automated Takeoff")
        self.setModal(True)
        self.resize(380, 230)

        self.setStyleSheet("""
            QDialog {
                background-color: #0b111c;
                border: 2px solid #00d4ff;
                border-radius: 12px;
            }
            QLabel {
                color: #dbe7ff;
            }
            QDoubleSpinBox {
                background-color: #0e1726;
                color: #00f5ff;
                font-size: 18px;
                font-weight: 800;
                border: 1px solid #1f3b5c;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton#takeoffBtn {
                background-color: #0088cc;
                color: #ffffff;
                font-weight: 800;
                padding: 8px 18px;
                border-radius: 6px;
                border: 1px solid #00d4ff;
            }
            QPushButton#takeoffBtn:hover {
                background-color: #00d4ff;
                color: #000000;
            }
            QPushButton#cancelBtn {
                background-color: #1a2333;
                color: #8fa0b5;
                font-weight: 600;
                padding: 8px 16px;
                border-radius: 6px;
                border: 1px solid #2d3b50;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title_lbl = QLabel("PARAMÈTRES DE DÉCOLLAGE" if is_fr else "TAKEOFF PARAMETERS")
        title_lbl.setStyleSheet("color: #00d4ff; font-weight: 800; font-size: 14px; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        form = QFormLayout()
        form.setSpacing(10)
        self.alt_spin = QDoubleSpinBox()
        self.alt_spin.setRange(1.0, 50.0)
        self.alt_spin.setSingleStep(0.5)
        self.alt_spin.setValue(default_alt)
        self.alt_spin.setSuffix(" m")
        form.addRow("Altitude cible :" if is_fr else "Target Altitude:", self.alt_spin)
        layout.addLayout(form)

        hint = QLabel(
            "Assurez-vous que l'espace aérien est dégagé et que le drone est armé."
            if is_fr
            else "Ensure clear airspace and armed state before confirming takeoff."
        )
        hint.setStyleSheet("color: #7b93ab; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Annuler" if is_fr else "Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        takeoff_btn = QPushButton("DÉCOLLER" if is_fr else "TAKEOFF")
        takeoff_btn.setObjectName("takeoffBtn")
        takeoff_btn.clicked.connect(self.accept)
        btn_row.addWidget(takeoff_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def get_altitude(parent: QWidget | None = None, default_alt: float = 5.0) -> float | None:
        dlg = TakeoffAltitudeDialog(default_alt=default_alt, parent=parent)
        if dlg.exec() == QDialog.Accepted:
            return dlg.alt_spin.value()
        return None


class KeyboardShortcutsDialog(QDialog):
    """Dialog displaying all operational keyboard shortcuts in a tactical layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        is_fr = getattr(parent, "current_language", "en") == "fr"
        self.setWindowTitle("Raccourcis Clavier" if is_fr else "Keyboard Shortcuts")
        self.resize(600, 480)

        self.setStyleSheet("""
            QDialog {
                background-color: #0b111c;
                border: 2px solid #265888;
                border-radius: 12px;
            }
            QLabel#title {
                color: #00d4ff;
                font-size: 16px;
                font-weight: 800;
                letter-spacing: 1px;
            }
            QLabel#catHeader {
                color: #f59e0b;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0.8px;
                margin-top: 8px;
                border-bottom: 1px solid #23354b;
                padding-bottom: 3px;
            }
            QLabel#keyBadge {
                background-color: #142032;
                color: #00f5ff;
                font-family: Consolas, monospace;
                font-size: 12px;
                font-weight: 700;
                border: 1px solid #1f3e60;
                border-radius: 4px;
                padding: 2px 8px;
            }
            QLabel#descLabel {
                color: #c0d1e5;
                font-size: 12px;
            }
            QPushButton#closeBtn {
                background-color: #1a293d;
                color: #dbe7ff;
                font-weight: 700;
                padding: 7px 20px;
                border: 1px solid #2a486c;
                border-radius: 6px;
            }
            QPushButton#closeBtn:hover {
                background-color: #00b4d8;
                color: #000000;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title_lbl = QLabel("CENTRE DES RACCOURCIS CLAVIER" if is_fr else "KEYBOARD SHORTCUTS CENTER")
        title_lbl.setObjectName("title")
        layout.addWidget(title_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(6)

        categories = [
            (
                "COMMANDES DE VOL & SÉCURITÉ" if is_fr else "FLIGHT CONTROLS & SAFETY",
                [
                    ("Ctrl + A", "Armer / Désarmer les moteurs" if is_fr else "Arm / Disarm motors"),
                    ("Ctrl + T", "Décollage automatique assisté" if is_fr else "Automated takeoff"),
                    ("Ctrl + R", "Retour automatique à la base (RTL)" if is_fr else "Return To Launch (RTL)"),
                    ("Ctrl + L", "Atterrissage automatique immédiat" if is_fr else "Automatic landing"),
                    ("Espace", "Maintien stationnaire (Hold / Pause)" if is_fr else "Hold position / Loiter"),
                    ("Ctrl + Shift + K", "ARRÊT D'URGENCE (Kill Motors)" if is_fr else "EMERGENCY STOP (Kill Motors)"),
                    ("1 .. 5", "Sélection rapide des modes de vol" if is_fr else "Quick flight mode selection"),
                ],
            ),
            (
                "CARTOGRAPHIE & NAVIGATION" if is_fr else "MAPPING & NAVIGATION",
                [
                    ("C", "Recentrer la carte sur le drone" if is_fr else "Recenter map on drone"),
                    ("F", "Basculer le suivi dynamique (Follow)" if is_fr else "Toggle dynamic drone follow"),
                    ("W", "Activer mode ajout de Waypoint" if is_fr else "Toggle add waypoint mode"),
                    ("Suppr", "Effacer tous les waypoints" if is_fr else "Clear all waypoints"),
                    ("Clic Droit", "Poser un waypoint sur la carte" if is_fr else "Place waypoint on map"),
                ],
            ),
            (
                "AFFICHAGE & VUES" if is_fr else "DISPLAY & VIEWS",
                [
                    ("M", "Basculer vers la vue Carte" if is_fr else "Switch to Map view"),
                    ("V", "Basculer vers la vue Vidéo Live" if is_fr else "Switch to Live video view"),
                    ("T", "Basculer vers la vue Thermique" if is_fr else "Switch to Thermal view"),
                    ("D", "Basculer vers la vue Télémétrie" if is_fr else "Switch to Telemetry DATA"),
                    ("O", "Changer le mode OSD (Full / Minimal / Off)" if is_fr else "Cycle Video OSD mode (Full / Minimal / Off)"),
                    ("P", "Afficher / masquer Picture-in-Picture (PiP)" if is_fr else "Toggle Picture-in-Picture (PiP)"),
                    ("F11", "Basculer Plein Écran" if is_fr else "Toggle Fullscreen"),
                    ("F1", "Afficher cette aide des raccourcis" if is_fr else "Show this shortcuts help"),
                ],
            ),
        ]

        for cat_name, items in categories:
            cat_lbl = QLabel(cat_name)
            cat_lbl.setObjectName("catHeader")
            c_layout.addWidget(cat_lbl)
            for key, desc in items:
                row = QHBoxLayout()
                row.setContentsMargins(6, 2, 6, 2)
                k_badge = QLabel(key)
                k_badge.setObjectName("keyBadge")
                k_badge.setFixedWidth(140)
                row.addWidget(k_badge)
                d_lbl = QLabel(desc)
                d_lbl.setObjectName("descLabel")
                row.addWidget(d_lbl, 1)
                c_layout.addLayout(row)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("Fermer" if is_fr else "Close")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)


class VideoSourceDialog(QDialog):
    def __init__(
        self,
        title: str,
        current_protocol: str,
        current_address: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel("Choisir le protocole video puis renseigner l'adresse du flux.")
        intro.setWordWrap(True)
        intro.setObjectName("pageSubtitle")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["RTSP", "UDP", "HTTP"])
        self.protocol_combo.setCurrentText(current_protocol if current_protocol in {"RTSP", "UDP", "HTTP"} else "RTSP")
        form.addRow("Protocole", self.protocol_combo)

        self.address_input = QLineEdit(current_address)
        self.address_input.setPlaceholderText("rtsp://..., udp://..., http://...")
        form.addRow("Adresse", self.address_input)
        layout.addLayout(form)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("metricHint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        language = getattr(parent, "current_language", "en")
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setText(UI_TEXTS.get(language, UI_TEXTS["en"])["cancel"])
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.protocol_combo.currentTextChanged.connect(self._update_hint)
        self._update_hint(self.protocol_combo.currentText())

    def _update_hint(self, protocol: str) -> None:
        hints = {
            "RTSP": "Exemple: rtsp://192.168.1.10:554/stream",
            "UDP": "Exemple: udp://@0.0.0.0:5000",
            "HTTP": "Exemple: http://192.168.1.10:8080/video",
        }
        self.hint_label.setText(hints.get(protocol, "Adresse video"))

    def source_profile(self) -> tuple[str, str]:
        return self.protocol_combo.currentText(), self.address_input.text().strip()


class OfflineMapZoneDialog(QDialog):
    def __init__(
        self,
        existing_zones: list[dict[str, object]],
        *,
        current_zoom: int,
        center_latitude: float | None,
        center_longitude: float | None,
        selected_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.language = getattr(parent, "current_language", "en")
        self.setWindowTitle("Zone hors ligne")
        self.resize(420, 240)
        self.action = "download"
        self._existing_zones = {
            str(zone.get("name", "")).strip(): zone
            for zone in existing_zones
            if str(zone.get("name", "")).strip()
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel("Nommer la zone et choisir la plage de zoom a telecharger pour le cache offline.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        layout.addLayout(form)

        self.name_combo = QComboBox()
        self.name_combo.setEditable(True)
        self.name_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for name in sorted(self._existing_zones):
            self.name_combo.addItem(name)
        default_name = f"Zone {datetime.now().strftime('%d-%m %H%M')}"
        self.name_combo.setCurrentText(selected_name or default_name)
        self.name_combo.currentTextChanged.connect(self._load_existing_zone)
        form.addRow("Nom", self.name_combo)

        self.zoom_min_spin = QSpinBox()
        self.zoom_min_spin.setRange(OfflineMapWidget.MIN_ZOOM, OfflineMapWidget.MAX_ZOOM)
        self.zoom_min_spin.setValue(max(OfflineMapWidget.MIN_ZOOM, current_zoom - 1))
        form.addRow("Zoom min", self.zoom_min_spin)

        self.zoom_max_spin = QSpinBox()
        self.zoom_max_spin.setRange(OfflineMapWidget.MIN_ZOOM, OfflineMapWidget.MAX_ZOOM)
        self.zoom_max_spin.setValue(min(OfflineMapWidget.MAX_ZOOM, current_zoom + 1))
        self.zoom_max_spin.valueChanged.connect(self._sync_zoom_bounds)
        self.zoom_min_spin.valueChanged.connect(self._sync_zoom_bounds)
        form.addRow("Zoom max", self.zoom_max_spin)

        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 6)
        self.padding_spin.setValue(1)
        form.addRow("Marge tuiles", self.padding_spin)

        center_text = "--"
        if center_latitude is not None and center_longitude is not None:
            center_text = f"{center_latitude:.5f}, {center_longitude:.5f}"
        self.center_label = QLabel(center_text)
        self.center_label.setWordWrap(True)
        form.addRow("Centre", self.center_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.update_button = QPushButton(self._text("save"))
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton(self._text("cancel"))
        self.ok_button.setDefault(True)
        self.update_button.clicked.connect(self._accept_update)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.update_button)
        button_row.addStretch(1)
        button_row.addWidget(self.ok_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self._load_existing_zone(self.name_combo.currentText())

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self.language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def _sync_zoom_bounds(self) -> None:
        if self.zoom_min_spin.value() > self.zoom_max_spin.value():
            sender = self.sender()
            if sender is self.zoom_min_spin:
                self.zoom_max_spin.setValue(self.zoom_min_spin.value())
            else:
                self.zoom_min_spin.setValue(self.zoom_max_spin.value())

    def _load_existing_zone(self, name: str) -> None:
        zone = self._existing_zones.get(name.strip())
        if zone is None:
            self.status_label.setText("Nouvelle zone offline.")
            return

        self.zoom_min_spin.setValue(int(zone.get("zoom_min", self.zoom_min_spin.value())))
        self.zoom_max_spin.setValue(int(zone.get("zoom_max", self.zoom_max_spin.value())))
        self.padding_spin.setValue(int(zone.get("padding_tiles", self.padding_spin.value())))
        self.status_label.setText("Zone existante detectee : la configuration sera mise a jour.")

    def accept(self) -> None:
        self.action = "download"
        self._accept_with_action()

    def _accept_update(self) -> None:
        self.action = "update"
        self._accept_with_action()

    def _accept_with_action(self) -> None:
        zone_name = self.name_combo.currentText().strip()
        if not zone_name:
            self.status_label.setText("Le nom de zone est obligatoire.")
            return
        if self.zoom_min_spin.value() > self.zoom_max_spin.value():
            self.status_label.setText("Le zoom min doit etre inferieur ou egal au zoom max.")
            return
        super().accept()

    def zone_spec(self) -> dict[str, object]:
        return {
            "name": self.name_combo.currentText().strip(),
            "zoom_min": int(self.zoom_min_spin.value()),
            "zoom_max": int(self.zoom_max_spin.value()),
            "padding_tiles": int(self.padding_spin.value()),
            "action": self.action,
        }


class OfflineMapZoneBrowserDialog(QDialog):
    def __init__(self, zones: list[dict[str, object]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.language = getattr(parent, "current_language", "en")
        self.setWindowTitle("Zones offline")
        self.resize(460, 400)
        self._zones = zones
        self.action = "open"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel("Choisir une zone offline ou lancer une action de gestion.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list_widget = QListWidget()
        for zone in zones:
            name = str(zone.get("name", "")).strip()
            if not name:
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, zone)
            subtitle = f"z{zone.get('zoom_min', '?')}..{zone.get('zoom_max', '?')}  |  {zone.get('tile_count', '?')} tuiles"
            item.setToolTip(subtitle)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_action("open"))
        self.list_widget.currentItemChanged.connect(self._update_details)
        layout.addWidget(self.list_widget, 1)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.open_button = QPushButton(self._text("open"))
        self.rename_button = QPushButton(self._text("rename"))
        self.update_button = QPushButton(self._text("modify"))
        self.delete_button = QPushButton(self._text("delete"))
        self.cancel_button = QPushButton(self._text("cancel"))
        for button in (self.open_button, self.rename_button, self.update_button, self.delete_button, self.cancel_button):
            action_row.addWidget(button)
        layout.addLayout(action_row)

        self.open_button.clicked.connect(lambda: self._accept_action("open"))
        self.rename_button.clicked.connect(lambda: self._accept_action("rename"))
        self.update_button.clicked.connect(lambda: self._accept_action("update"))
        self.delete_button.clicked.connect(lambda: self._accept_action("delete"))
        self.cancel_button.clicked.connect(self.reject)

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self.details_label.setText("Aucune zone offline enregistree pour le moment.")

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self.language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def _accept_action(self, action: str) -> None:
        if self.selected_zone() is None:
            self.details_label.setText("Selectionner une zone d'abord.")
            return
        self.action = action
        self.accept()

    def _update_details(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            self.details_label.setText("Aucune zone selectionnee.")
            return
        zone = current.data(Qt.UserRole) or {}
        latitude = zone.get("center_latitude")
        longitude = zone.get("center_longitude")
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            center_text = f"{float(latitude):.5f}, {float(longitude):.5f}"
        else:
            center_text = "--"
        details = (
            f"Centre: {center_text}\n"
            f"Zoom: {zone.get('zoom_min', '?')} -> {zone.get('zoom_max', '?')}  |  Affichage: {zone.get('display_zoom', zone.get('zoom_min', '?'))}\n"
            f"Tuiles: {zone.get('tile_count', '?')}  |  Mise a jour: {zone.get('updated_at', '--')}"
        )
        self.details_label.setText(details)

    def selected_zone(self) -> dict[str, object] | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        zone = item.data(Qt.UserRole)
        return zone if isinstance(zone, dict) else None


class OfflineMapDownloadDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.language = getattr(parent, "current_language", "en")
        self.setWindowTitle("Telechargement offline")
        self.resize(420, 180)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.title_label = QLabel("Preparation du telechargement...")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.status_label = QLabel("0 / 0")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.action_button = QPushButton(self._text("cancel"))
        self.action_button.clicked.connect(self._handle_action_button)
        layout.addWidget(self.action_button, 0, Qt.AlignRight)

        self._download_finished = False
        self._allow_close = False

    def _text(self, key: str) -> str:
        return UI_TEXTS.get(self.language, UI_TEXTS["en"]).get(key, UI_TEXTS["en"].get(key, key))

    def set_language(self, language: str) -> None:
        self.language = language if language in UI_TEXTS else "en"
        if not self._download_finished and self.action_button.isEnabled():
            self.action_button.setText(self._text("cancel"))

    def _present(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent_geometry = parent.frameGeometry()
            self.move(
                parent_geometry.center().x() - self.width() // 2,
                parent_geometry.center().y() - self.height() // 2,
            )
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def begin(self, zone_name: str | None, total: int) -> None:
        prefix = zone_name or "Zone offline"
        self.title_label.setText(f"Telechargement de {prefix}")
        self.status_label.setText(f"0 / {max(0, total)} tuiles")
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(0)
        self.action_button.setText(self._text("cancel"))
        self.action_button.setEnabled(True)
        self._download_finished = False
        self._allow_close = False
        self._present()

    def update_progress(self, done: int, total: int) -> None:
        total = max(1, total)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(max(0, min(done, total)))
        self.status_label.setText(f"{max(0, done)} / {total} tuiles")

    def finish(self, message: str, success: int, total: int, *, cancelled: bool = False) -> None:
        total = max(1, total)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(max(0, min(success, total)))
        self.title_label.setText(message)
        if cancelled:
            self.status_label.setText(f"Annule a {success} / {total} tuiles")
        else:
            self.status_label.setText(f"{success} / {total} tuiles")
        self.action_button.setText("OK")
        self.action_button.setEnabled(True)
        self._download_finished = True
        self._allow_close = True
        self._present()

    def show_message(self, title: str, status: str) -> None:
        self.title_label.setText(title)
        self.status_label.setText(status)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.action_button.setText("OK")
        self.action_button.setEnabled(True)
        self._download_finished = True
        self._allow_close = True
        self._present()

    def mark_cancelling(self) -> None:
        self.title_label.setText("Annulation du telechargement...")
        self.action_button.setText(self._text("cancelling"))
        self.action_button.setEnabled(False)

    def _handle_action_button(self) -> None:
        if self._download_finished:
            self.accept()
            return
        self.cancel_requested.emit()

    def reject(self) -> None:
        if self._allow_close:
            super().reject()
