"""
audio/devices.py

Audio device enumeration (via sounddevice/PortAudio) plus Windows-only
functionality to detect VB-CABLE and to switch the *system default*
recording/playback device.

Device enumeration for the GUI (drop-down lists, VB-CABLE detection)
uses `sounddevice`, which works cross-platform and is what the mixer
and player also use to open audio streams.

Switching the *Windows system default* endpoint requires talking to
Windows Core Audio directly. There is no public Win32 API for this;
the Sound control panel itself calls an internal COM interface named
`IPolicyConfig`. This is a well-known technique used by common,
legitimate audio-switching utilities and is implemented here using
`pycaw` (for robust IMMDevice / property-store access) plus a small
custom COM interface binding for the `SetDefaultEndpoint` method that
pycaw itself does not expose.
"""

from __future__ import annotations

import logging
import platform
import warnings
from dataclasses import dataclass
from typing import List, Optional

import sounddevice as sd

# pycaw emits numerous harmless COM property enumeration warnings on
# some audio devices that don't expose all property stores. Suppress
# them at the source so the user isn't bombarded.
warnings.filterwarnings("ignore", message="COMError attempting to get property")
warnings.filterwarnings("ignore", message=".*attempting to get property.*")

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


@dataclass
class AudioDevice:
    """A single audio device as reported by PortAudio."""

    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    hostapi: int

    @property
    def is_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0

    @property
    def is_vb_cable_input(self) -> bool:
        """True if this is the VB-CABLE recording endpoint, i.e.
        what you'd record *from* to capture InstantBoard's mixed audio.
        Known names: 'CABLE Output', 'CABLE In', 'CABLE In 16ch'."""
        name = self.name.lower()
        return "cable output" in name or "cable in" in name

    @property
    def is_vb_cable_output(self) -> bool:
        """True if this is the VB-CABLE playback endpoint InstantBoard
        should render its mixed audio to. Known names: 'CABLE Input'."""
        return "cable input" in self.name.lower()


def list_devices() -> List[AudioDevice]:
    """Return every audio device PortAudio can see."""
    devices = []
    try:
        raw_devices = sd.query_devices()
    except Exception as exc:  # pragma: no cover - defensive, PortAudio init issues
        logger.error("Failed to query audio devices: %s", exc)
        return []

    for idx, info in enumerate(raw_devices):
        devices.append(
            AudioDevice(
                index=idx,
                name=info.get("name", f"Device {idx}"),
                max_input_channels=info.get("max_input_channels", 0),
                max_output_channels=info.get("max_output_channels", 0),
                default_samplerate=info.get("default_samplerate", 44100.0),
                hostapi=info.get("hostapi", 0),
            )
        )
    return devices


def list_input_devices() -> List[AudioDevice]:
    return [d for d in list_devices() if d.is_input]


def list_output_devices() -> List[AudioDevice]:
    return [d for d in list_devices() if d.is_output]


def find_vb_cable_input() -> Optional[AudioDevice]:
    """Find the 'CABLE Output' recording endpoint (i.e. what you'd record
    from to hear InstantBoard's mixed output)."""
    for device in list_input_devices():
        if device.is_vb_cable_input:
            return device
    return None


def find_vb_cable_output() -> Optional[AudioDevice]:
    """Find the 'CABLE Input' playback endpoint InstantBoard should render to."""
    for device in list_output_devices():
        if device.is_vb_cable_output:
            return device
    return None


def is_vb_cable_installed() -> bool:
    return find_vb_cable_input() is not None or find_vb_cable_output() is not None


# ==========================================================================
# Windows default recording/playback device switching
# ==========================================================================

_POLICY_CONFIG_CLSID = "{870af99c-171d-4f9e-af0d-e63df40c2bc9}"
_IPOLICY_CONFIG_IID = "{f8679f50-850a-41cf-9c72-430f290290c8}"

E_ROLE_CONSOLE = 0
E_ROLE_MULTIMEDIA = 1
E_ROLE_COMMUNICATIONS = 2


class DeviceSwitchError(Exception):
    """Raised when the Windows default audio device cannot be changed."""


class WindowsDefaultDeviceSwitcher:
    """Switches the Windows *system default* recording/playback device.

    This class only functions on Windows and only when `pycaw` and
    `comtypes` are installed. On any other platform, or if COM setup
    fails, every method raises `DeviceSwitchError` with a clear
    explanation so the GUI can show a friendly warning instead of
    crashing.
    """

    def __init__(self) -> None:
        self._available = False
        self._error: Optional[str] = None
        if not IS_WINDOWS:
            self._error = "Default device switching is only supported on Windows."
            return
        try:
            import comtypes  # noqa: F401
            from pycaw.pycaw import AudioUtilities  # noqa: F401
            self._available = True
        except ImportError as exc:
            self._error = f"Missing dependency for device switching: {exc}"

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> Optional[str]:
        return self._error

    # ------------------------------------------------------------------
    # PortAudio-to-Windows name mapping
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # PortAudio-to-Windows name mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _portaudio_to_windows_name(portaudio_name: str) -> str:
        """Map a PortAudio device name (as shown in the GUI combo box) to
        a Windows Core Audio friendly name we can search for.

        PortAudio shows names like:
          - "Microphone (Realtek Audio)"              (DirectSound)
          - "CABLE Output (VB-Audio Virtual Cable)"   (MME/WDM-KS)
          - "CABLE In 16ch (VB-Audio Virtual Cable)"  (MME/WDM-KS)
          - "Speakers (MR710)"                        (DirectSound)
          - "Microsoft Sound Mapper - Input"          (MME)

        The strategy is:
          1. Remove the "Microsoft Sound Mapper" / "Primary Sound" prefixes
             entirely (they are virtual devices with no real Windows endpoint).
          2. For everything else, extract just the base name before the
             trailing parenthetical driver suffix.
        """
        pa_lower = portaudio_name.lower().strip()

        # "Microsoft Sound Mapper - Input" / "Microsoft Sound Mapper - Output"
        # These are PortAudio virtual devices; skip them entirely.
        if pa_lower.startswith("microsoft sound mapper"):
            return ""  # Empty string signals "skip this device"

        # "Primary Sound Capture Driver" / "Primary Sound Driver"
        if pa_lower.startswith("primary sound"):
            return ""

        # Keep the full name including the model in parentheses.
        # "Microphone (MR710)" should stay as "Microphone (MR710)" not become "Microphone"
        # because "Microphone" alone would match the wrong device.
        return portaudio_name

    # ------------------------------------------------------------------
    # Endpoint resolution
    # ------------------------------------------------------------------
    def _find_endpoint_id(self, friendly_name_substring: str, capture: bool) -> str:
        """Resolve a friendly device name to a Windows Core Audio endpoint
        ID string.

        This uses pycaw's AudioUtilities to enumerate all Windows audio
        endpoints and find the one whose FriendlyName best matches the
        given device name.  The matching is done in multiple passes with
        increasing leniency.
        """
        from pycaw.pycaw import AudioUtilities

        # Apply PortAudio-to-Windows name mapping
        search_name = self._portaudio_to_windows_name(friendly_name_substring)
        if not search_name:
            raise DeviceSwitchError(
                f"'{friendly_name_substring}' is a virtual device (Microsoft Sound "
                f"Mapper) and cannot be switched. Select a physical device instead."
            )

        target = search_name.lower()

        try:
            devices = AudioUtilities.GetAllDevices()
        except Exception as exc:
            raise DeviceSwitchError(f"Could not enumerate audio endpoints: {exc}") from exc

        if not devices:
            raise DeviceSwitchError("No audio endpoints found on this system")

        # --- Pass 1.5: pre-filter by device type BEFORE matching ----------
        # This prevents "Microphone (MR710)" from matching "Speakers (Steam Streaming Microphone)"
        if capture:
            # For microphones, ONLY search in capture devices
            search_devices = []
            for device in devices:
                try:
                    dataflow = getattr(device, 'dataflow', None)
                    if dataflow == 1:  # 1 = capture
                        search_devices.append(device)
                    elif dataflow is None:
                        # Fallback: check friendly name
                        friendly_lower = (device.FriendlyName or "").lower()
                        is_speaker = any(x in friendly_lower for x in ['speaker', 'headphone', 'playback', 'render'])
                        if not is_speaker:
                            search_devices.append(device)
                except Exception:
                    continue
            devices = search_devices if search_devices else devices

        # --- Pass 1: exact substring match on FriendlyName ----------
        matches = []
        for device in devices:
            try:
                if device.FriendlyName and target in device.FriendlyName.lower():
                    matches.append((device, 3))
            except Exception:
                continue

        # --- Pass 2: match by significant words (words > 3 chars) ---
        if not matches:
            words = [w.rstrip(",").strip() for w in target.replace("-", " ").split()
                     if len(w.rstrip(",").strip()) > 3]
            for device in devices:
                try:
                    friendly = (device.FriendlyName or "").lower()
                    score = sum(1 for w in words if w in friendly)
                    # Require at least 2 significant words to match
                    if score >= max(2, len(words) // 2):
                        matches.append((device, 1))
                except Exception:
                    continue

        # --- Pass 4: sort by score and pick the best ---------------
        if matches:
            matches.sort(key=lambda x: -x[1])
            best = matches[0][0]
            logger.info(
                "Resolved '%s' -> Windows endpoint '%s' (score=%d, id=%s)",
                friendly_name_substring, best.FriendlyName,
                matches[0][1], best.id
            )
            return best.id

        # --- No match found: list available devices ----------------
        try:
            avail = []
            for d in AudioUtilities.GetAllDevices():
                try:
                    if d.FriendlyName:
                        # Show capture vs render distinction
                        direction = "IN" if capture else "OUT"
                        avail.append(f"{d.FriendlyName}")
                except Exception:
                    pass
            avail_list = ", ".join(avail[:15])
            if len(avail) > 15:
                avail_list += f" ... and {len(avail)-15} more"
        except Exception:
            avail_list = "(could not enumerate)"

        raise DeviceSwitchError(
            f"Could not find a Windows audio endpoint matching "
            f"'{friendly_name_substring}' (searched for '{search_name}'). "
            f"Available devices: [{avail_list}]"
        )

    # ------------------------------------------------------------------
    # Public switching API
    # ------------------------------------------------------------------
    def set_default_recording_device(self, device_name: str) -> None:
        """Set the Windows system default *recording* device to the
        endpoint whose friendly name contains `device_name`."""
        self._set_default_device(device_name, capture=True)

    def set_default_playback_device(self, device_name: str) -> None:
        """Set the Windows system default *playback* device to the
        endpoint whose friendly name contains `device_name`."""
        self._set_default_device(device_name, capture=False)

    def _set_default_device(self, device_name: str, capture: bool) -> None:
        if not self._available:
            raise DeviceSwitchError(self._error or "Default device switching unavailable.")

        import comtypes
        from comtypes import GUID, COMMETHOD, HRESULT, IUnknown, CoCreateInstance, CLSCTX_INPROC_SERVER
        import ctypes

        comtypes.CoInitialize()
        try:
            device_id = self._find_endpoint_id(device_name, capture)

            class IPolicyConfig(IUnknown):
                """Minimal binding of the undocumented IPolicyConfig
                interface, exposing only SetDefaultEndpoint (the method
                the Windows Sound control panel uses internally). The
                preceding vtable slots must still be declared, even
                though InstantBoard never calls them, so that the vtable
                offsets line up correctly."""

                _iid_ = GUID(_IPOLICY_CONFIG_IID)
                _methods_ = [
                    COMMETHOD([], HRESULT, "GetMixFormat"),
                    COMMETHOD([], HRESULT, "GetDeviceFormat"),
                    COMMETHOD([], HRESULT, "ResetDeviceFormat"),
                    COMMETHOD([], HRESULT, "SetDeviceFormat"),
                    COMMETHOD([], HRESULT, "GetProcessingPeriod"),
                    COMMETHOD([], HRESULT, "SetProcessingPeriod"),
                    COMMETHOD([], HRESULT, "GetShareMode"),
                    COMMETHOD([], HRESULT, "SetShareMode"),
                    COMMETHOD([], HRESULT, "GetPropertyValue"),
                    COMMETHOD([], HRESULT, "SetPropertyValue"),
                    COMMETHOD(
                        [],
                        HRESULT,
                        "SetDefaultEndpoint",
                        (["in"], ctypes.c_wchar_p, "deviceId"),
                        (["in"], ctypes.c_int, "role"),
                    ),
                    COMMETHOD([], HRESULT, "SetEndpointVisibility"),
                ]

            policy_config = CoCreateInstance(
                GUID(_POLICY_CONFIG_CLSID),
                interface=IPolicyConfig,
                clsctx=CLSCTX_INPROC_SERVER,
            )

            for role in (E_ROLE_CONSOLE, E_ROLE_MULTIMEDIA, E_ROLE_COMMUNICATIONS):
                policy_config.SetDefaultEndpoint(device_id, role)

            logger.info(
                "Switched default %s device to '%s'",
                "recording" if capture else "playback",
                device_name,
            )
        except DeviceSwitchError:
            raise
        except Exception as exc:
            logger.error("Failed to switch default device: %s", exc)
            raise DeviceSwitchError(str(exc)) from exc
        finally:
            comtypes.CoUninitialize()
