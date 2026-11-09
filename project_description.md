# InstantBoard — Comprehensive Project Description & Technical Documentation

**InstantBoard** is a modern, production-grade Windows desktop application built with **Python 3.10+**, **PySide6 (Qt6)**, **CoreAudio (pycaw/comtypes)**, and **VB-Audio Virtual Cable**. It serves as an all-in-one soundboard, local neural voice synthesizer, universal media audio injector, and **real-time cross-lingual speech translator with zero-shot voice cloning**.

InstantBoard routes audio directly into Windows communication apps (such as Discord, Zoom, Microsoft Teams, Google Meet, OBS Studio, and in-game voice chat) via VB-CABLE virtual audio endpoints without requiring manual device swapping.

---

## 1. System Architecture & High-Level Overview

```
                                  ┌────────────────────────────────────────────────────────┐
                                  │               InstantBoard (PySide6 GUI)               │
                                  │  ┌────────────┬────────────┬────────────┬────────────┐ │
                                  │  │   Sounds   │    TTS     │   Links    │ Translator │ │
                                  │  │(MyInstants)│(Pocket-TTS)│  (yt-dlp)  │  (S2ST)    │ │
                                  │  └─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┘ │
                                  └────────┼────────────┼────────────┼────────────┼────────┘
                                           │            │            │            │
                                           ▼            ▼            ▼            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                InstantBoard Audio Engine                               │
│                                                                                        │
│   ┌───────────────────────────┐                ┌───────────────────────────────────┐   │
│   │ MicrophoneRecorder        │                │ Active Sounds & Decoders          │   │
│   │ (sounddevice InputStream) │                │ (MyInstants, Pocket-TTS, yt-dlp)  │   │
│   └─────────────┬─────────────┘                └─────────────────┬─────────────────┘   │
│                 │                                                │                     │
│                 │ (Non-blocking Listener)                        │                     │
│                 ├───────────────────────────────┐                │                     │
│                 │                               │                │                     │
│                 ▼                               ▼                ▼                     │
│   ┌───────────────────────────┐   ┌────────────────────────────────────────────────┐   │
│   │ Live Translator Pipeline  │   │ AudioMixer (48 kHz / 32-bit Float Internal)    │   │
│   │ (VAD → ASR → MT → TTS)    │   │                                                │   │
│   └─────────────┬─────────────┘   │   - Soundboard Volume Rail                     │   │
│                 │                 │   - Microphone Volume Rail                     │   │
│                 │ (Synthesized    │   - Monitor Volume Rail                        │   │
│                 │  Cloned Speech) │   - Soft Limiter (tanh clipping protection)    │   │
│                 └────────────────►│   - Dynamic Physical Mic Suppression           │   │
│                                   └──────────────────────┬─────────────────────────┘   │
└──────────────────────────────────────────────────────────┼─────────────────────────────┘
                                                           │
                                            ┌──────────────┴──────────────┐
                                            ▼                             ▼
                                ┌──────────────────────┐      ┌──────────────────────┐
                                │   Local Headphones   │      │   VB-CABLE Input     │
                                │   (Monitor Stream)   │      │  (Playback Endpoint) │
                                └──────────────────────┘      └──────────┬───────────┘
                                                                         │
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │   VB-CABLE Output    │
                                                              │ (Recording Endpoint) │
                                                              └──────────┬───────────┘
                                                                         │
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │ Discord / Zoom /     │
                                                              │ Teams / OBS / Games  │
                                                              └──────────────────────┘
```

---

## 2. Core Functional Pillars

### 2.1. Live Voice Translator (Zero-Shot Cross-Lingual Speech-to-Speech)
The Live Translator allows users to speak in one language (e.g., **Urdu**) while call participants hear them in another (e.g., **English**), or speak **English** and have callers hear **Arabic**, rendered in a **recognizable clone of the user's voice**:
- **Automatic Language Identification (LID)**: Built-in Whisper detection with rolling hysteresis to prevent language flapping on noise, plus manual overrides (`Auto`, `Urdu`, `English`, `Arabic`).
- **Faithful Clause Translation**: Powered by quantized CTranslate2 NLLB-200. Translates incremental grammatical clauses, preserving negation (*not / نہیں / لا*), numbers, names, and first-person perspective with zero conversational hallucination.
- **Cross-Lingual Voice Cloning**: Integrates zero-shot synthesis conditioning. Users enroll with a 5-second clean mic sample; the engine extracts vocal pitch, formants, and resonance, synthesizing the target speech in the user's vocal timbre.
- **Microphone Suppression**: When translator mode is active, the physical microphone is suppressed from the call output feed (VB-CABLE). Callers hear **only** the translated speech in the cloned voice without raw voice leakage.
- **RTL/LTR Adaptive Transcripts**: Real-time dual display with native Right-to-Left (RTL) layout formatting for Urdu and Arabic scripts.
- **Safety & Control**: Includes Push-to-Talk (Hold) and an **EMERGENCY STOP** button that instantly clears queues, aborts inference, and silences playback.

### 2.2. Soundboard & MyInstants Explorer
- **Search & Trending**: Explores, searches, and parses audio clips directly from [MyInstants](https://www.myinstants.com).
- **Overlapping Playback**: Multiple sound clips mix concurrently without cutting off earlier sounds.
- **Disk Caching**: Automatically saves fetched sounds locally (`cache/`) with MD5 hashing and bounded size limits.
- **Card-Based UI**: Modern grid layout with hover animations, volume indicators, and favorite bookmarks.

### 2.3. Local Neural Text-to-Speech (TTS)
- **Engine**: Powered by **Kyutai Pocket-TTS** (~100M parameter local neural model running fully on CPU).
- **Catalogue**: 23 diverse conversational voices (Jane, Alba, Bill, Caro, Peter, Anna, Estelle, Giovanni, Juergen, Lola, etc.).
- **Debounced Auto-Speech**: Automatically generates audio 500ms after the user stops typing.
- **Mixer Injection**: Streams synthesized speech directly into the mixer for broadcasting to calls.

### 2.4. Universal Media Link Extractor (Links Tab)
- **Engine**: Powered by `yt-dlp`.
- **Supported Sources**: YouTube, TikTok, Instagram Reels, Twitter/X, SoundCloud, Reddit, Twitch clips, and more.
- **Instant Injection**: Extracts audio tracks on the fly and routes them into the virtual audio broadcast feed.

### 2.5. Audio Routing & Windows CoreAudio Integration
- **Windows CoreAudio COM Integration**: Uses `pycaw` and `comtypes` (`IPolicyConfig`) to dynamically switch the Windows default communications recording device.
- **VB-CABLE Virtual Audio**:
  - InstantBoard renders to **CABLE Input** (playback endpoint).
  - Discord, Zoom, or Teams records from **CABLE Output** (recording endpoint).
- **Three Independent Volume Rails**:
  - **Monitor Volume**: Local speaker/headphone loudness.
  - **Microphone Volume**: Physical mic passthrough level (when translator is off).
  - **Soundboard Volume**: Sound clip and media volume sent to voice calls.

---

## 3. Strict Project-Local Storage Architecture

To guarantee privacy, portability, and clean dependency boundaries, all machine learning weights, tokenizers, caches, runtime files, and temporary assets are restricted to paths beneath `PROJECT_ROOT`:

```
e:\Agnific\SoundBoard\
├── models/
│   ├── vad/                # Silero VAD ONNX models
│   ├── asr/                # Faster-Whisper ASR models (large-v3-turbo, base)
│   ├── translation/        # NLLB-200 CTranslate2 INT8 models
│   ├── tts/                # Voice cloning TTS models (XTTS-v2)
│   └── manifests/          # Model ID specifications, licenses, checksums
├── .runtime/
│   ├── cache/              # Process-local HF_HOME, TORCH_HOME, NUMBA caches
│   ├── tmp/                # Atomic download staging & temporary buffers
│   ├── logs/               # Session logs and crash diagnostics
│   ├── benchmarks/         # Automated latency & RTF benchmark reports
│   └── venvs/              # Isolated worker virtual environments (when needed)
├── data/
│   ├── voice_profiles/     # Enrolled user voice samples and conditioning metadata
│   └── translator/         # Session history and exportable transcripts
```

### Process Environment Bootstrap
Before ML packages are imported, `translator/bootstrap.py` executes:
- Resolves `PROJECT_ROOT` strictly from file location (never `os.getcwd()`).
- Sets process-local environment variables:
  - `HF_HOME = PROJECT_ROOT / ".runtime/cache/huggingface"`
  - `TORCH_HOME = PROJECT_ROOT / ".runtime/cache/torch"`
  - `NUMBA_CACHE_DIR = PROJECT_ROOT / ".runtime/cache/numba"`
  - `TEMP = PROJECT_ROOT / ".runtime/tmp"`
- Verifies that target directories are not external symlinks/junctions.
- Sets `local_files_only=True` and `HF_HUB_OFFLINE=1` during inference.

---

## 4. Repository Structure

```
instantboard/
├── audio/
│   ├── decoder.py          # Audio file decoding (soundfile with ffmpeg-python fallback)
│   ├── devices.py          # Audio device enumeration & Windows COM endpoint switching
│   ├── mixer.py            # Multitrack audio mixer, soft limiter, translator queue, mic suppression
│   ├── player.py           # Playback queue lifecycle and callbacks
│   └── recorder.py         # Continuous mic capture with non-blocking listener fan-out
├── benchmarks/
│   └── benchmark_pipeline.py # Automated latency, RTF, RAM, and backlog benchmarking harness
├── gui/
│   ├── link_player_widget.py # yt-dlp media downloader panel
│   ├── main_window.py      # Top-level window, tabs container, hotkeys, shutdown lifecycle
│   ├── player_widget.py    # Bottom control deck: volume sliders and mode toggles
│   ├── search_widget.py    # MyInstants search grid, pagination, favorites
│   ├── settings_dialog.py  # Device selector, hotkey configuration, cache cleanup
│   ├── translator_widget.py # Live Translator panel (controls, RTL transcripts, voice recorder)
│   └── tts_widget.py       # Kyutai Pocket-TTS local neural synthesis panel
├── myinstants/
│   ├── api.py              # Asynchronous MyInstants web crawler
│   └── parser.py           # HTML parser for sound cards and audio metadata
├── resources/
│   ├── icons.py            # Dynamic SVG icon loader with tinting
│   └── theme.py            # Dark theme stylesheet (QSS) with violet/green accents
├── tests/
│   ├── test_contracts_and_pipeline.py # Pipeline contracts, cancellation, voice profiles
│   ├── test_mixer_routing.py          # Mixer mic suppression & audio feeding tests
│   ├── test_storage_bootstrap.py      # Local storage, cache isolation, offline flags
│   ├── test_translation_and_asr.py    # Translation fidelity (Urdu/English/Arabic)
│   └── test_vad_stream.py             # Silero VAD frame buffering & state tests
├── translator/
│   ├── asr.py              # Faster-Whisper ASR & language detection with hysteresis
│   ├── bootstrap.py        # Centralized path bootstrap & project-local env isolation
│   ├── contracts.py        # Typed stage contracts (AudioFrame, TranscriptUnit, etc.)
│   ├── models/
│   │   ├── manager.py      # Atomic downloader, space verifier, staging installer
│   │   └── manifest.py     # Official model specifications and capability registry
│   ├── pipeline.py         # Multi-threaded streaming translator orchestrator
│   ├── profiles.py         # Voice profile enrollment & reference audio manager
│   ├── translation.py      # CTranslate2 NLLB-200 INT8 translation engine
│   ├── tts.py              # High-level voice cloning TTS client
│   ├── tts_worker.py       # Isolated TTS worker process (JSON-lines IPC)
│   └── vad.py              # Streaming Silero VAD (ONNX) with recurrent hidden state
├── utils/
│   ├── cache.py            # Disk cache with MD5 hashing and bounded size limits
│   └── settings.py         # JSON settings persistence (hotkeys, volumes, devices)
├── main.py                 # Application bootstrap and Qt event loop
└── requirements.txt        # Frozen dependency specification
```

---

## 5. Technology Stack

| Layer | Component | Purpose |
|---|---|---|
| **GUI Framework** | PySide6 (Qt 6.11+) | Cross-platform UI, dark QSS styling, event loop |
| **Audio I/O** | `sounddevice` + PortAudio | Low-latency audio stream capture and playback |
| **DSP & Mixing** | `numpy` 2.x | Vectorized float32 multitrack mixing and soft limiting |
| **Windows Routing** | `pycaw`, `comtypes` | Windows CoreAudio `IPolicyConfig` default endpoint switching |
| **Voice Activity Detection** | Silero VAD v5 (ONNX Runtime) | CPU-based 512-sample frame voice detection |
| **Speech Recognition** | `faster-whisper` (CTranslate2) | Multilingual ASR and language detection (Urdu, English, Arabic) |
| **Machine Translation** | CTranslate2 + NLLB-200 INT8 | Faithful clause translation (Urdu $\leftrightarrow$ English, English $\leftrightarrow$ Arabic) |
| **Voice Cloning TTS** | XTTS-v2 / Isolated IPC Worker | Zero-shot cross-lingual voice synthesis in user's vocal timbre |
| **Local Neural TTS** | `pocket-tts` (Kyutai) | 100M parameter CPU neural text-to-speech |
| **Media Downloader** | `yt-dlp` | Video-to-audio extraction from web URLs |
| **Web Scraping** | `requests`, `beautifulsoup4` | MyInstants sound directory scraping |
| **Global Keybinds** | `keyboard` | Global Windows hotkey hooks |

---

## 6. Verification and Testing

InstantBoard includes a comprehensive automated test suite and benchmark harness:

### 6.1. Running Unit Tests
```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
- Validates project-local directory confinement and rejection of external junctions.
- Tests frame-exact VAD buffering, silence hangover, and state clearing.
- Tests translation accuracy, negation preservation, and language pair registry.
- Verifies that `AudioMixer` suppresses physical mic audio when translator mode is active.
- Verifies emergency stop queue flushing and cancellation tokens.

### 6.2. Running Pipeline Benchmarks
```powershell
# Urdu -> English benchmark
.\venv\Scripts\python.exe benchmarks/benchmark_pipeline.py --source-lang ur --target-lang en --iterations 3

# English -> Arabic benchmark
.\venv\Scripts\python.exe benchmarks/benchmark_pipeline.py --source-lang en --target-lang ar --iterations 3
```
- Measures per-stage compute times (VAD, ASR, Translation, TTS).
- Measures Real-Time Factor (RTF) of the voice cloning synthesizer.
- Records memory usage and backlog accumulation under synthetic speech fixtures.
- Generates structured JSON reports in `.runtime/benchmarks/`.
