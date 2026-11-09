# InstantBoard

A polished Windows desktop soundboard, local neural voice studio, and **real-time cross-lingual voice translator with zero-shot voice cloning**. Plays sound effects, text-to-speech, online media audio, and translated speech directly into your microphone input — perfect for Discord, Zoom, Microsoft Teams, Google Meet, OBS Studio, and gaming voice chat.

Built with **Python**, **PySide6 (Qt6)**, **CTranslate2**, **ONNX Runtime**, and **VB-Audio Virtual Cable**.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Windows](https://img.shields.io/badge/Windows-10%2F11-green)
![License](https://img.shields.io/badge/License-MIT-purple)
![AI Models](https://img.shields.io/badge/AI-100%25%20Local-orange)

---

## What It Does

InstantBoard bridges desktop audio and virtual microphone routing on Windows. It eliminates manual audio device switching by programmatically routing audio through **VB-CABLE** while managing physical microphone passthrough.

### Key Capabilities

1. **🎙️ Live Voice Translator (Zero-Shot Voice Cloning)**
   - Speak in **Urdu** and callers hear **English**, or speak **English** and callers hear **Arabic**.
   - **Clones your voice**: Synthesizes the translated output in your own vocal timbre and pitch from a 5-second enrollment sample.
   - **Automatic Language Detection**: Auto-detects input language or lets you manually set source/target pairs.
   - **Microphone Suppression**: While translator mode is active, your raw microphone audio is suppressed from the call so callers hear **only** the translated speech.
   - **Emergency Stop & Push-to-Talk**: Instant silence button and hold-to-speak mode.
   - **RTL Transcripts**: Live dual transcripts with native Right-to-Left rendering for Urdu and Arabic.

2. **🔊 Soundboard & MyInstants Explorer**
   - Search, browse trending sounds, and trigger clips from [MyInstants](https://www.myinstants.com).
   - **Overlapping playback**: Play multiple sounds simultaneously with automatic soft-limiting to prevent clipping.
   - **Local disk caching**: Sounds are cached locally for offline and instant repeat playback.

3. **🗣️ Local Neural Text-to-Speech (Pocket-TTS)**
   - 23 natural conversational voices powered by Kyutai Pocket-TTS (~100M parameter model running on CPU).
   - Auto-speaks 500ms after you stop typing.

4. **🔗 Media Link Audio Extractor (yt-dlp)**
   - Paste video/audio links from YouTube, TikTok, Instagram Reels, Twitter/X, SoundCloud, or Reddit.
   - Extracts and streams audio directly through your virtual microphone.

5. **⚡ Global Hotkeys & Independent Volumes**
   - Bind favorite sounds to global keyboard shortcuts (`F1–F12`, `Ctrl+Alt+...`) triggered from any game or full-screen app.
   - 3 independent volume sliders: **Monitor** (your headphones), **Microphone**, and **Soundboard**.

---

## How the Audio Routing Works

```
                               ┌────────────────────────┐
                               │ InstantBoard Interface │
                               └───────────┬────────────┘
                                           │
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                           InstantBoard Audio Engine                           │
│                                                                               │
│  [Physical Mic] ──► (Translator Active?)                                      │
│                           │                                                   │
│                           ├── YES ──► VAD/ASR ──► Translation ──► Cloned TTS  │
│                           │           (Raw mic suppressed from call feed) │   │
│                           │                                               │   │
│                           └── NO  ──► Normal Mic Passthrough              │   │
│                                                   │                       │   │
│  [Soundboard / TTS / Links] ──────────────────────┼───────────────────────┤   │
│                                                   ▼                       ▼   │
│                                          ┌─────────────────┐ ┌────────────┐   │
│                                          │  Monitor Output │ │  Mix Output│   │
│                                          │  (Headphones)   │ │  (CABLE In)│   │
│                                          └─────────────────┘ └──────┬─────┘   │
└─────────────────────────────────────────────────────────────────────┼─────────┘
                                                                      ▼
                                                           ┌────────────────────┐
                                                           │   VB-CABLE Input   │
                                                           └──────────┬─────────┘
                                                                      │
                                                                      ▼
                                                           ┌────────────────────┐
                                                           │   VB-CABLE Output  │
                                                           │ (Recording Device) │
                                                           └──────────┬─────────┘
                                                                      │
                                                                      ▼
                                                           ┌────────────────────┐
                                                           │ Discord / Zoom /   │
                                                           │ Games / OBS        │
                                                           └────────────────────┘
```

- InstantBoard sends mixed audio to **CABLE Input** (playback device).
- Discord, Zoom, Microsoft Teams, or OBS records from **CABLE Output** (recording device).

---

## Requirements

| Component | Requirement |
|---|---|
| **Operating System** | Windows 10 / 11 (64-bit) |
| **Python** | Python 3.10, 3.11, or 3.12 |
| **Virtual Cable** | [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (Free) |
| **Hardware** | Any modern multi-core CPU, 8 GB+ RAM (Models run on CPU/AVX2) |

---

## Setup & Installation

### 1. Install VB-CABLE
1. Download and install [VB-CABLE Driver from vb-audio.com](https://vb-audio.com/Cable/).
2. **Restart your PC** after installation so Windows registers the virtual audio endpoints:
   - **CABLE Input** appears under *Playback devices*.
   - **CABLE Output** appears under *Recording devices*.

### 2. Clone and Setup Environment
```powershell
# Clone repository
git clone https://github.com/RasikhAli/InstantBoard.git
cd SoundBoard

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Launch InstantBoard
```powershell
python main.py
```

---

## User Guide

### 🎙️ Using the Live Translator
1. Open the **Live Translator** tab in InstantBoard.
2. **Enroll Your Voice (One-time, 5 seconds)**:
   - Click **Record Voice (5s)** and speak naturally into your microphone, or click **Import WAV** to use an existing clean sample.
   - Select your newly created profile from the dropdown.
3. **Select Language Direction**:
   - **Source**: `Auto (Detect)` or `Urdu (اردو)` or `English`.
   - **Target**: `English` or `Arabic (العربية)`.
4. **Start Translation**:
   - Click **Start Live Translation** for continuous mode, or hold **Push-to-Talk**.
   - Speak in Urdu $\to$ callers on Discord or Zoom hear you in English with your cloned voice.
   - Your physical microphone is automatically suppressed so callers only hear the translated output.
   - Hit **EMERGENCY STOP** at any time to instantly flush queues and silence audio.

### 🔊 Using the Soundboard
1. Click the **Sounds** tab.
2. Type in the search bar or browse trending clips from MyInstants.
3. Click **Play** on any card to trigger it into your microphone.
4. Click the **Heart icon** to favorite a sound for hotkey binding.

### 🗣️ Using Text-to-Speech (Pocket-TTS)
1. Click the **TTS** tab.
2. Select one of the 23 conversational voices.
3. Type your text. 500ms after you stop typing, the model synthesizes and plays the speech into your microphone.

### 🔗 Using the Link Player
1. Click the **Links** tab.
2. Paste any media link (YouTube, TikTok, Instagram Reel, Twitter video).
3. Click **Play** — InstantBoard downloads and injects the audio track on the fly.

### 🎛️ Volume Controls
In the bottom control bar:
- **Playback Volume**: Adjusts loudness in your local headphones/speakers.
- **Microphone Volume**: Adjusts physical microphone sensitivity in calls (when translator is off).
- **Soundboard Volume**: Adjusts media loudness sent to voice calls.
- **Soundboard / Normal Mode**: Toggle continuous virtual mic routing for streaming.

---

## Testing & Verification

InstantBoard includes an automated test suite and benchmark harness:

### Run Unit Tests
```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
Verifies strict project-local storage, VAD frame buffering, Urdu/English/Arabic translation fidelity, physical mic suppression, and cancellation tokens.

### Run Performance Benchmarks
```powershell
# Benchmark Urdu -> English
.\venv\Scripts\python.exe benchmarks/benchmark_pipeline.py --source-lang ur --target-lang en --iterations 3

# Benchmark English -> Arabic
.\venv\Scripts\python.exe benchmarks/benchmark_pipeline.py --source-lang en --target-lang ar --iterations 3
```
Measures per-stage compute times, Real-Time Factor (RTF), memory consumption, and backlog.

---

## Project Structure

```
instantboard/
├── audio/
│   ├── decoder.py          # Audio decoding (soundfile with ffmpeg fallback)
│   ├── devices.py          # Device discovery and Windows CoreAudio switching
│   ├── mixer.py            # Multitrack mixer, soft limiter, mic suppression
│   ├── player.py           # High-level playback lifecycle
│   └── recorder.py         # Mic capture with non-blocking listener fan-out
├── benchmarks/
│   └── benchmark_pipeline.py # Automated latency and RTF benchmark harness
├── gui/
│   ├── link_player_widget.py # yt-dlp media downloader panel
│   ├── main_window.py      # Main window, tabs container, hotkey manager
│   ├── player_widget.py    # Bottom control deck: volume sliders and mode toggles
│   ├── search_widget.py    # MyInstants search grid and pagination
│   ├── settings_dialog.py  # Device selector and hotkey manager dialog
│   ├── translator_widget.py # Live Translator panel with RTL transcripts
│   └── tts_widget.py       # Kyutai Pocket-TTS local synthesis panel
├── myinstants/
│   ├── api.py              # MyInstants web crawler
│   └── parser.py           # Sound card and metadata parser
├── resources/
│   ├── icons.py            # Dynamic SVG icon loader
│   └── theme.py            # Dark modern stylesheet (QSS)
├── tests/
│   ├── test_contracts_and_pipeline.py
│   ├── test_mixer_routing.py
│   ├── test_storage_bootstrap.py
│   ├── test_translation_and_asr.py
│   └── test_vad_stream.py
├── translator/
│   ├── asr.py              # Faster-Whisper ASR & language detection
│   ├── bootstrap.py        # Strict project-local storage bootstrap
│   ├── contracts.py        # Typed stage contracts and data models
│   ├── models/             # Manifests, capability registry, atomic installer
│   ├── pipeline.py         # Multi-threaded streaming translator pipeline
│   ├── profiles.py         # Voice profile enrollment & reference manager
│   ├── translation.py      # CTranslate2 NLLB-200 faithful translation
│   ├── tts.py              # Voice cloning TTS client
│   ├── tts_worker.py       # Isolated worker process (JSON-lines IPC)
│   └── vad.py              # Streaming Silero VAD (ONNX) with recurrent state
├── utils/
│   ├── cache.py            # Disk cache with MD5 hashing
│   └── settings.py         # JSON settings persistence
├── main.py                 # Application bootstrap entry point
└── requirements.txt        # Frozen Python dependencies
```

---

## Troubleshooting

- **"VB-CABLE not detected"**:
  Ensure VB-CABLE is installed from [vb-audio.com](https://vb-audio.com/Cable/) and that you have rebooted Windows. In Windows Sound settings, verify that `CABLE Input` appears under Playback devices and `CABLE Output` appears under Recording devices.
- **Callers can't hear the soundboard or translation**:
  In Discord, Zoom, or Teams audio settings, change the **Input Device (Microphone)** to **CABLE Output**.
- **Translating language**:
  Make sure your microphone is selected in the bottom device bar or settings dialog. Click **Record Voice (5s)** to capture your voice profile before starting translation for the best cloning quality.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
