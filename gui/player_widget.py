"""
gui/player_widget.py

The bottom control panel: volume sliders, input/output device
selectors, the Normal/Soundboard mic-switch buttons, and the status
indicator (VB-CABLE detection, mixer state).
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from audio.devices import (
    AudioDevice,
    DeviceSwitchError,
    WindowsDefaultDeviceSwitcher,
    find_vb_cable_input,
    find_vb_cable_output,
    is_vb_cable_installed,
    list_input_devices,
    list_output_devices,
)
from audio.mixer import AudioMixer
from utils.icons import get_icon
from utils.settings import SettingsManager

logger = logging.getLogger(__name__)


def _labeled_slider(label_text: str, initial_value: int) -> tuple[QVBoxLayout, QSlider, QLabel]:
    layout = QVBoxLayout()
    layout.setSpacing(2)
    header = QHBoxLayout()
    label = QLabel(label_text)
    label.setObjectName("MutedLabel")
    value_label = QLabel(f"{initial_value}%")
    value_label.setObjectName("MutedLabel")
    header.addWidget(label)
    header.addStretch(1)
    header.addWidget(value_label)
    layout.addLayout(header)

    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(initial_value)
    layout.addWidget(slider)
    slider.valueChanged.connect(lambda v: value_label.setText(f"{v}%"))
    return layout, slider, value_label


class PlayerWidget(QWidget):
    """Bottom panel exposing the mixer's live controls."""

    def __init__(self, settings: SettingsManager, mixer: AudioMixer, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._mixer = mixer
        self._switcher = WindowsDefaultDeviceSwitcher()

        self._build_ui()
        self._populate_devices()
        self._restore_settings()
        self._refresh_vb_cable_status()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setObjectName("BottomPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(10)

        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(24)

        pb_layout, self.playback_slider, _ = _labeled_slider("Playback Volume", 80)
        mic_layout, self.mic_slider, _ = _labeled_slider("Microphone Volume", 80)
        sb_layout, self.soundboard_slider, _ = _labeled_slider("Soundboard Volume", 80)

        for layout in (pb_layout, mic_layout, sb_layout):
            container = QWidget()
            container.setLayout(layout)
            sliders_row.addWidget(container, stretch=1)

        self.playback_slider.valueChanged.connect(self._on_playback_volume_changed)
        self.mic_slider.valueChanged.connect(self._on_mic_volume_changed)
        self.soundboard_slider.valueChanged.connect(self._on_soundboard_volume_changed)

        root.addLayout(sliders_row)

        devices_row = QHBoxLayout()
        devices_row.setSpacing(16)

        output_layout = QVBoxLayout()
        output_label = QLabel("Output Device (Broadcast)")
        output_label.setObjectName("MutedLabel")
        output_layout.addWidget(output_label)
        self.output_combo = QComboBox()
        self.output_combo.currentIndexChanged.connect(self._on_output_device_changed)
        output_layout.addWidget(self.output_combo)
        devices_row.addLayout(output_layout, stretch=2)

        input_layout = QVBoxLayout()
        input_label = QLabel("Input Device (Microphone)")
        input_label.setObjectName("MutedLabel")
        input_layout.addWidget(input_label)
        self.input_combo = QComboBox()
        self.input_combo.currentIndexChanged.connect(self._on_input_device_changed)
        input_layout.addWidget(self.input_combo)
        devices_row.addLayout(input_layout, stretch=2)

        mode_layout = QVBoxLayout()
        mode_label = QLabel("Windows Default Recording Device")
        mode_label.setObjectName("MutedLabel")
        mode_layout.addWidget(mode_label)
        mode_buttons = QHBoxLayout()
        self.normal_button = QPushButton("Normal")
        self.normal_button.clicked.connect(self._on_normal_clicked)
        self.soundboard_button = QPushButton("Soundboard")
        self.soundboard_button.setIcon(get_icon("soundboard", 16))
        self.soundboard_button.clicked.connect(self._on_soundboard_clicked)
        mode_buttons.addWidget(self.normal_button)
        mode_buttons.addWidget(self.soundboard_button)
        mode_layout.addLayout(mode_buttons)
        devices_row.addLayout(mode_layout, stretch=2)

        root.addLayout(devices_row)

        status_row = QHBoxLayout()
        self.vb_cable_status_icon = QLabel()
        self.vb_cable_status_label = QLabel()
        self.vb_cable_status_label.setObjectName("StatusLabel")
        status_row.addWidget(self.vb_cable_status_icon)
        status_row.addWidget(self.vb_cable_status_label)
        status_row.addStretch(1)
        self.mixer_status_label = QLabel("Soundboard mixer: idle")
        self.mixer_status_label.setObjectName("MutedLabel")
        status_row.addWidget(self.mixer_status_label)
        root.addLayout(status_row)

    # ------------------------------------------------------------------
    # Device population
    # ------------------------------------------------------------------
    def _populate_devices(self) -> None:
        self.output_combo.blockSignals(True)
        self.input_combo.blockSignals(True)
        self.output_combo.clear()
        self.input_combo.clear()

        # Add "System Default" as the first option (index None = let sounddevice decide)
        self.output_combo.addItem("System Default", None)
        self.input_combo.addItem("System Default", None)

        for device in list_output_devices():
            # Skip virtual Microsoft Sound Mapper devices - they can't be
            # switched via Windows Core Audio and selecting them causes issues.
            name_lower = device.name.lower()
            if "microsoft sound mapper" in name_lower or "primary sound" in name_lower:
                continue
            self.output_combo.addItem(device.name, device.index)

        for device in list_input_devices():
            name_lower = device.name.lower()
            if "microsoft sound mapper" in name_lower or "primary sound" in name_lower:
                continue
            # Skip VB-CABLE and virtual audio endpoints from the microphone
            # selector - they should only be used through the Soundboard button
            if any(x in name_lower for x in ["cable", "vb-audio", "virtual audio", "point"]):
                continue
            self.input_combo.addItem(device.name, device.index)

        self.output_combo.blockSignals(False)
        self.input_combo.blockSignals(False)

    def _restore_settings(self) -> None:
        self.playback_slider.setValue(int(self._settings.get("playback_volume", 0.8) * 100))
        self.mic_slider.setValue(int(self._settings.get("microphone_volume", 0.8) * 100))
        self.soundboard_slider.setValue(int(self._settings.get("soundboard_volume", 0.8) * 100))

        last_output = self._settings.get("last_output_device")
        last_input = self._settings.get("last_microphone")
        self._select_combo_by_name(self.output_combo, last_output)
        self._select_combo_by_name(self.input_combo, last_input)

        self._start_monitor_stream()

    @staticmethod
    def _select_combo_by_name(combo: QComboBox, name: Optional[str]) -> None:
        if not name:
            if combo.count() > 0:
                combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if combo.itemText(i) == name:
                combo.setCurrentIndex(i)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _refresh_vb_cable_status(self) -> None:
        if is_vb_cable_installed():
            self.vb_cable_status_icon.setPixmap(get_icon("soundboard", 16, "#3ddc97").pixmap(16, 16))
            self.vb_cable_status_label.setText("VB-CABLE detected")
            self.vb_cable_status_label.setStyleSheet("color: #3ddc97;")
        else:
            self.vb_cable_status_icon.setPixmap(get_icon("warning", 16).pixmap(16, 16))
            self.vb_cable_status_label.setText(
                "VB-CABLE not detected - install it from vb-audio.com to route audio into calls"
            )
            self.vb_cable_status_label.setStyleSheet("color: #ff5c7a;")

    # ------------------------------------------------------------------
    # Volume handlers
    # ------------------------------------------------------------------
    def _on_playback_volume_changed(self, value: int) -> None:
        self._mixer.playback_volume = value / 100.0
        self._settings.set("playback_volume", value / 100.0)

    def _on_mic_volume_changed(self, value: int) -> None:
        self._mixer.microphone_volume = value / 100.0
        self._settings.set("microphone_volume", value / 100.0)

    def _on_soundboard_volume_changed(self, value: int) -> None:
        self._mixer.soundboard_volume = value / 100.0
        self._settings.set("soundboard_volume", value / 100.0)

    # ------------------------------------------------------------------
    # Device handlers
    # ------------------------------------------------------------------
    def _current_output_device(self) -> Optional[AudioDevice]:
        idx = self.output_combo.currentData()
        if idx is None:
            return None
        return next((d for d in list_output_devices() if d.index == idx), None)

    def _current_input_device(self) -> Optional[AudioDevice]:
        idx = self.input_combo.currentData()
        if idx is None:
            return None
        return next((d for d in list_input_devices() if d.index == idx), None)

    def _start_monitor_stream(self) -> None:
        device = self._current_output_device()
        try:
            self._mixer.start_monitor(device.index if device else None)
        except Exception as exc:
            logger.error("Could not start monitor stream: %s", exc)

    def _on_output_device_changed(self, _index: int) -> None:
        device = self._current_output_device()
        if device:
            self._settings.set("last_output_device", device.name)
        self._start_monitor_stream()

    def _on_input_device_changed(self, _index: int) -> None:
        device = self._current_input_device()
        if device:
            self._settings.set("last_microphone", device.name)

    # ------------------------------------------------------------------
    # Normal / Soundboard mode switching
    # ------------------------------------------------------------------
    def _on_normal_clicked(self) -> None:
        device = self._current_input_device()
        if not device:
            self.mixer_status_label.setText("No microphone selected")
            return
        self._mixer.stop_broadcast()
        try:
            self._switcher.set_default_recording_device(device.name)
            # Use PortAudio name in display message since that's what the user sees
            self.mixer_status_label.setText(f"Windows default recording device: {device.name}")
        except DeviceSwitchError as exc:
            self.mixer_status_label.setText(f"Could not switch device: {exc}")
            logger.warning("Device switch failed: %s", exc)

    def _on_soundboard_clicked(self) -> None:
        cable_out = find_vb_cable_output()
        cable_in = find_vb_cable_input()
        mic = self._current_input_device()
        monitor_device = self._current_output_device()

        if not cable_out or not cable_in:
            self.mixer_status_label.setText("VB-CABLE is required for Soundboard mode")
            return
        if not mic:
            self.mixer_status_label.setText("No microphone selected")
            return

        # Ensure the monitor (speakers) stream is running on the user's
        # chosen output device BEFORE we start the broadcast, so switching
        # the default recording device doesn't affect what we hear.
        if monitor_device:
            try:
                self._mixer.start_monitor(monitor_device.index)
            except Exception:
                pass

        # Re-query cable_out index right before use in case devices changed
        cable_out = find_vb_cable_output()
        if not cable_out:
            self.mixer_status_label.setText("VB-CABLE output device disappeared")
            return

        try:
            # Start broadcast with sounds only (no microphone mixing)
            # This avoids the robotic voice caused by timing issues
            self._mixer.start_broadcast_sounds_only(
                device_index=cable_out.index,
            )
        except Exception as exc:
            self.mixer_status_label.setText(f"Could not start soundboard mixer: {exc}")
            logger.error("Failed to start broadcast: %s", exc)
            return

        # Switch to VB-CABLE so communication apps can hear the sounds,
        # then immediately switch back to the user's normal microphone.
        # This way, communication apps will mix both sources automatically.
        try:
            cable_names = ["CABLE Output", "CABLE In 16ch", "CABLE In", "VB-Audio Virtual Cable"]
            switched = False
            last_error = None
            for name in cable_names:
                try:
                    self._switcher.set_default_recording_device(name)
                    switched = True
                    break
                except DeviceSwitchError as e:
                    last_error = e
                    continue
            if not switched:
                raise last_error or DeviceSwitchError(
                    "Could not find any VB-CABLE recording endpoint"
                )
            
            # Immediately switch back to the user's normal microphone
            # Communication apps will mix both sources
            try:
                self._switcher.set_default_recording_device(mic.name)
                self.mixer_status_label.setText(
                    "Soundboard mode active - sounds routed to VB-CABLE, mic stays on MR710"
                )
            except DeviceSwitchError:
                self.mixer_status_label.setText(
                    "Soundboard active - sounds on VB-CABLE (mic may need manual switch)"
                )
        except DeviceSwitchError as exc:
            self.mixer_status_label.setText(
                f"Mixer running, but could not switch Windows default device: {exc}"
            )
            logger.warning("Device switch failed: %s", exc)

    def refresh_devices(self) -> None:
        """Re-scan audio devices (called from the Settings dialog / Refresh)."""
        self._populate_devices()
        self._restore_settings()
        self._refresh_vb_cable_status()

    def shutdown(self) -> None:
        self._mixer.shutdown()
