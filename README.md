# InstantBoard

A polished Windows soundboard that plays sound effects directly into your microphone input — perfect for Discord, Zoom, games, and streams. Built with Python, PySide6, and VB-CABLE.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Windows](https://img.shields.io/badge/Windows-10%2F11-green)

---

## What it does

InstantBoard lets you search, browse, and trigger sound clips from [MyInstants](https://www.myinstants.com) with one click or a global hotkey. When a sound plays, InstantBoard automatically:

1. **Switches your default recording device** to VB-CABLE (`CABLE Output`)
2. **Routes the audio** through VB-CABLE so communication apps pick it up immediately
3. **Switches back** to your normal microphone when the clip ends

No manual device switching. No missed audio at the start of a clip.

---

## Features

- **One-click playback** — search MyInstants, hit play, and the sound triggers instantly
- **Auto device switching** — seamlessly routes audio to your mic input during playback and restores it afterward
- **Overlapping playback** — trigger multiple sounds at once; they mix together naturally with volume control
- **Global hotkeys** — assign keyboard shortcuts to your favorite sounds and trigger them from anywhere
- **Trending & search** — browse trending sounds or search for anything you need
- **Volume controls** — independent sliders for playback, microphone, and soundboard levels
- **Polished dark UI** — clean, modern interface with animated cards and status indicators

---

## Requirements

| Component | Version |
|-----------|---------|
| Python | 3.10 or newer |
| OS | Windows 10 / 11 |
| VB-CABLE | [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) |

### Python dependencies

- `PySide6` — Qt UI framework
- `sounddevice` + `numpy` — real-time audio mixing
- `soundfile` — MP3/WAV decoding
- `pycaw` + `comtypes` — Windows default audio device switching
- `keyboard` *(optional)* — global hotkeys
- `requests` + `beautifulsoup4` — MyInstants browsing

---

## Setup

### 1. Install VB-CABLE

Download and install [VB-CABLE from vb-audio.com](https://vb-audio.com/Cable/). This creates two virtual audio endpoints:
- **CABLE Input** — playback endpoint (what InstantBoard writes to)
- **CABLE Output** — recording endpoint (what Discord / Zoom / OBS listens to)

Restart your PC after installing.

### 2. Clone and install

```bash
git clone https://github.com/yourname/instantboard.git
cd instantboard
python -m venv venv
.\venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. Run

```bash
python main.py
```

---

## How to use

### Basic playback

1. Search for a sound in the search bar, or browse the trending grid
2. Click the **play button** on any card
3. The sound plays through your speakers *and* routes into your microphone input via VB-CABLE
4. When the clip ends, your default microphone is restored automatically

### Soundboard mode (manual)

If you want continuous soundboard routing (e.g., for streaming), click the **Soundboard** button in the bottom panel. This keeps VB-CABLE active even between clips. Click **Normal** to return to your regular microphone.

### Global hotkeys

1. Favorite a sound by clicking the heart icon on its card
2. Open **Settings** (gear icon)
3. Assign a hotkey combination to the favorited sound
4. Trigger it from anywhere — even when InstantBoard is minimized

### Volume controls

Use the sliders in the bottom panel to adjust:
- **Playback Volume** — local speaker monitoring
- **Microphone Volume** — your mic level in the mixed output
- **Soundboard Volume** — sound effect loudness

---

## Troubleshooting

**"VB-CABLE not detected"**
- Make sure VB-CABLE is installed and you've restarted Windows after installation
- In Windows Sound settings, verify that "CABLE Input" appears under Playback devices and "CABLE Output" under Recording devices

**No sound in Discord / Zoom**
- Make sure the app's input device is set to "CABLE Output"
- Try the **Soundboard** button in InstantBoard for continuous routing
- Check that your microphone isn't muted in Windows

**Audio is choppy or robotic**
- Close other apps that might be using the audio device
- Make sure your sample rate is consistent (InstantBoard uses 48 kHz internally)

---

## Project structure

```
instantboard/
├── audio/
│   ├── decoder.py      # MP3/WAV decoding
│   ├── devices.py      # Audio device enumeration and Windows default switching
│   ├── mixer.py        # Real-time mixing engine (sounds + mic → output)
│   ├── player.py       # High-level playback API
│   └── recorder.py     # Live microphone capture
├── gui/
│   ├── main_window.py  # Application window and hotkey manager
│   ├── player_widget.py # Bottom control panel (volumes, devices, mode)
│   └── search_widget.py # Search bar and sound card grid
├── myinstants/
│   ├── api.py          # MyInstants web client
│   └── parser.py       # Sound metadata parsing
├── utils/
│   ├── cache.py        # Local audio file caching
│   ├── icons.py        # SVG icon loader
│   └── settings.py     # JSON settings persistence
├── main.py             # Entry point
└── requirements.txt    # Python dependencies
```

---

## License

MIT — feel free to fork, modify, and share.

---

*Made with care for streamers, gamers, and anyone who loves a good soundboard.*
