"""
audio/windows_audio.py

Windows-specific audio utilities for InstantBoard that complement the
cross-platform device enumeration in `audio/devices.py`.

This module provides:
  * A convenience wrapper around the Windows Core Audio COM APIs for
    enumerating audio endpoints with richer metadata (device GUIDs,
    device state, friendly names as seen by Windows itself).
  * A function to retrieve the *current* Windows default recording
    endpoint, so the GUI can show which device is active.
  * A function to test whether a given PortAudio device index
    corresponds to a Windows audio endpoint that is currently active
    (not disabled / unplugged), which helps the GUI avoid selecting
    a device that will fail at stream-open time.

All functions in this module are no-ops (returning sensible defaults)
on non-Windows platforms, so importing the module is always safe.
"""

from __future__ import annotations

import logging
import platform
from typing import Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


def get_windows_default_recording_device() -> Optional[str]:
    """Return the friendly name of the current Windows default recording
    device, or None if the information cannot be obtained.

    This is useful for the GUI to display which microphone Windows is
    currently using as the default, and to verify that the device
    switching worked correctly.
    """
    if not IS_WINDOWS:
        return None
    try:
        from pycaw.pycaw import AudioUtilities, EDataFlow, ERole
        devices = AudioUtilities.GetAllDevices()
        # Get the default device for capture (recording) in the
        # communications role, which is what most chat apps use.
        default = AudioUtilities.GetDefaultDevice(
            EDataFlow.eCapture.value, ERole.eCommunications.value
        )
        if default is not None:
            return default.FriendlyName
        # Fallback: iterate and find the first active input device
        for device in devices:
            try:
                from pycaw.pycaw import DEVICE_STATE
                if device.state == DEVICE_STATE.ACTIVE.value:
                    return device.FriendlyName
            except Exception:
                continue
    except ImportError:
        logger.debug("pycaw not available; cannot query Windows default device")
    except Exception as exc:
        logger.debug("Could not query Windows default recording device: %s", exc)
    return None


def is_windows_device_active(portaudio_name: str) -> bool:
    """Check whether a PortAudio device name corresponds to a Windows
    audio endpoint that is currently active (not disabled, unplugged or
    otherwise unavailable).

    This helps the GUI avoid selecting a device that PortAudio reports
    but that Windows considers inactive, which would cause
    sounddevice.InputStream / OutputStream to fail at open time.
    """
    if not IS_WINDOWS:
        return True  # Assume active on non-Windows
    try:
        from pycaw.pycaw import AudioUtilities, DEVICE_STATE
        target = portaudio_name.lower()
        for device in AudioUtilities.GetAllDevices():
            try:
                friendly = (device.FriendlyName or "").lower()
                if target in friendly or friendly in target:
                    return device.state == DEVICE_STATE.ACTIVE.value
            except Exception:
                continue
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Could not check device state: %s", exc)
    # If we can't determine the state, assume active (let PortAudio
    # report the error if it fails).
    return True


def get_windows_device_id(portaudio_name: str) -> Optional[str]:
    """Resolve a PortAudio device name to a Windows Core Audio endpoint
    ID string. Returns None if no matching endpoint is found.

    The endpoint ID is useful for logging and diagnostics, and can be
    passed to Windows Core Audio APIs that require an ID rather than a
    friendly name.
    """
    if not IS_WINDOWS:
        return None
    try:
        from pycaw.pycaw import AudioUtilities
        target = portaudio_name.lower()
        for device in AudioUtilities.GetAllDevices():
            try:
                friendly = (device.FriendlyName or "").lower()
                if target in friendly or friendly in target:
                    return device.id
            except Exception:
                continue
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Could not resolve device ID: %s", exc)
    return None


def get_all_windows_devices() -> list[dict]:
    """Return a list of all Windows audio endpoints with their friendly
    names, IDs, states and data flow directions.

    This is primarily useful for diagnostic logging (e.g. dumping the
    full device list to the log file when debugging device switching
    issues).
    """
    result: list[dict] = []
    if not IS_WINDOWS:
        return result
    try:
        from pycaw.pycaw import AudioUtilities, DEVICE_STATE
        for device in AudioUtilities.GetAllDevices():
            try:
                result.append({
                    "id": getattr(device, "id", "?"),
                    "friendly_name": getattr(device, "FriendlyName", "?"),
                    "state": _device_state_name(getattr(device, "state", -1)),
                })
            except Exception:
                continue
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Could not enumerate Windows devices: %s", exc)
    return result


def _device_state_name(state: int) -> str:
    """Map a DEVICE_STATE integer to a human-readable name."""
    from pycaw.pycaw import DEVICE_STATE
    mapping = {
        DEVICE_STATE.ACTIVE.value: "ACTIVE",
        DEVICE_STATE.DISABLED.value: "DISABLED",
        DEVICE_STATE.NOTPRESENT.value: "NOTPRESENT",
        DEVICE_STATE.UNPLUGGED.value: "UNPLUGGED",
    }
    return mapping.get(state, f"UNKNOWN({state})")