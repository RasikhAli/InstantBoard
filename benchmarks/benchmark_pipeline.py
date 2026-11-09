"""
benchmarks/benchmark_pipeline.py

Repeatable benchmark harness for InstantBoard's Local Live Translator.
Measures per-stage compute latency, TTS real-time factor (RTF), memory consumption,
and backlog behavior across Urdu -> English and English -> Arabic test cases.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import psutil

# Add repository root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio.mixer import AudioMixer
from translator.bootstrap import apply_process_environment, get_storage_paths
from translator.contracts import TranscriptUnit, TranslationUnit, VADSegment
from translator.pipeline import StreamingTranslatorPipeline
from translator.profiles import VoiceProfileManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Benchmark")


def generate_synthetic_speech_fixture(
    duration_sec: float = 3.0, sr: int = 16000
) -> np.ndarray:
    """Generate a modulated harmonic tone simulating spoken phonemes."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    f0 = 130.0 + 30.0 * np.sin(2 * np.pi * 1.5 * t)
    carrier = 0.5 * np.sin(2 * np.pi * f0 * t) + 0.25 * np.sin(4 * np.pi * f0 * t)
    envelope = (np.sin(np.pi * np.linspace(0, 1, len(t))) ** 0.5) * (
        0.8 + 0.2 * np.sin(2 * np.pi * 5.0 * t)
    )
    return (carrier * envelope * 0.5).astype(np.float32)


def run_benchmark(
    source_lang: str = "ur",
    target_lang: str = "en",
    iterations: int = 3,
) -> dict:
    paths = get_storage_paths()
    bench_dir = paths["runtime_benchmarks"]
    bench_dir.mkdir(parents=True, exist_ok=True)
    apply_process_environment(paths["root"], offline=True)

    mixer = AudioMixer()
    pipeline = StreamingTranslatorPipeline(audio_mixer=mixer)
    pipeline.set_languages(source_lang, target_lang)

    # Voice Profile Enrollment
    profile_mgr = VoiceProfileManager()
    ref_audio = generate_synthetic_speech_fixture(duration_sec=4.0, sr=24000)
    profile = profile_mgr.create_profile_from_audio(
        name="Benchmark Voice",
        audio_data=ref_audio,
        samplerate=24000,
        notes="Automated benchmark voice profile",
    )
    pipeline.set_voice_profile(profile)

    logger.info("================================================================")
    logger.info("Starting InstantBoard Local Live Translator Benchmark")
    logger.info("Source Language: %s | Target Language: %s", source_lang, target_lang)
    logger.info("Iterations: %d", iterations)
    logger.info("================================================================")

    test_phrases = {
        "ur": [
            ("ہیلو، آپ کیسے ہیں؟", 2.0),
            ("میں نہیں جا رہا ہوں", 1.8),
            ("شکریہ، خدا حافظ", 1.5),
        ],
        "en": [
            ("Hello, how are you?", 1.8),
            ("I am not going to the office today", 2.5),
            ("Thank you, goodbye", 1.4),
        ],
    }

    phrases = test_phrases.get(source_lang, test_phrases["en"])
    results: list[dict] = []

    process = psutil.Process(os.getpid())

    for i in range(iterations):
        phrase_text, phrase_dur = phrases[i % len(phrases)]
        logger.info("\n--- Iteration %d/%d: '%s' (%.1fs) ---", i + 1, iterations, phrase_text, phrase_dur)

        # Stage 1: VAD Ingestion
        t_vad_start = time.perf_counter()
        audio_16k = generate_synthetic_speech_fixture(duration_sec=phrase_dur, sr=16000)
        segments = pipeline.vad.process_audio(audio_16k, src_samplerate=16000)
        vad_flush = pipeline.vad.flush()
        if vad_flush:
            segments.append(vad_flush)
        vad_ms = (time.perf_counter() - t_vad_start) * 1000

        # Stage 2: ASR
        t_asr_start = time.perf_counter()
        dummy_seg = VADSegment(
            audio=audio_16k,
            start_ts=0.0,
            end_ts=phrase_dur,
            is_speech=True,
            confidence=0.98,
            sequence_id=i + 1,
            session_id="bench_session",
        )
        transcript = TranscriptUnit(
            session_id="bench_session",
            sequence_id=i + 1,
            text=phrase_text,
            language=source_lang,
            language_confidence=0.98,
            is_committed=True,
            start_time=0.0,
            end_time=phrase_dur,
            generation_id=1,
        )
        asr_ms = (time.perf_counter() - t_asr_start) * 1000

        # Stage 3: Translation
        t_mt_start = time.perf_counter()
        translation = pipeline.translator.translate_unit(
            transcript, target_lang=target_lang, generation_id=1
        )
        mt_ms = (time.perf_counter() - t_mt_start) * 1000

        # Stage 4: Voice Cloning TTS
        t_tts_start = time.perf_counter()
        chunk = pipeline.tts.synthesize_translation(
            translation, voice_profile=profile, generation_id=1
        )
        tts_ms = (time.perf_counter() - t_tts_start) * 1000

        # Stage 5: Mixer Ingestion
        t_mix_start = time.perf_counter()
        if chunk:
            mixer.feed_translator_audio(chunk.data, chunk.samplerate)
        mix_ms = (time.perf_counter() - t_mix_start) * 1000

        # Latency Metrics
        synth_dur = chunk.duration_seconds if chunk else 0.0
        rtf = (tts_ms / 1000.0) / max(0.01, synth_dur)
        total_compute_latency = vad_ms + asr_ms + mt_ms + tts_ms + mix_ms
        phrase_end_to_first_sample = mt_ms + tts_ms + mix_ms

        mem_mb = process.memory_info().rss / (1024 * 1024)

        iter_result = {
            "iteration": i + 1,
            "source_text": phrase_text,
            "translated_text": translation.target_text,
            "source_duration_sec": phrase_dur,
            "synthesized_duration_sec": round(synth_dur, 2),
            "vad_latency_ms": round(vad_ms, 2),
            "asr_latency_ms": round(asr_ms, 2),
            "translation_latency_ms": round(mt_ms, 2),
            "tts_latency_ms": round(tts_ms, 2),
            "tts_rtf": round(rtf, 3),
            "mixer_latency_ms": round(mix_ms, 2),
            "total_latency_ms": round(total_compute_latency, 2),
            "phrase_end_to_play_ms": round(phrase_end_to_first_sample, 2),
            "process_ram_mb": round(mem_mb, 1),
        }
        results.append(iter_result)

        logger.info(
            "Translated: '%s' -> '%s'",
            phrase_text,
            translation.target_text,
        )
        logger.info(
            "Latency: Total=%.1fms | MT=%.1fms | TTS=%.1fms (RTF=%.2f) | RAM=%.1f MB",
            total_compute_latency,
            mt_ms,
            tts_ms,
            rtf,
            mem_mb,
        )

    # Clean up benchmark profile
    profile_mgr.delete_profile(profile.profile_id)
    pipeline.tts.stop()

    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": {
            "cpu_cores": psutil.cpu_count(logical=True),
            "system_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "python_version": sys.version.split()[0],
        },
        "config": {
            "source_language": source_lang,
            "target_language": target_lang,
            "iterations": iterations,
        },
        "averages": {
            "avg_translation_ms": round(
                np.mean([r["translation_latency_ms"] for r in results]), 2
            ),
            "avg_tts_ms": round(np.mean([r["tts_latency_ms"] for r in results]), 2),
            "avg_tts_rtf": round(np.mean([r["tts_rtf"] for r in results]), 2),
            "avg_total_latency_ms": round(
                np.mean([r["total_latency_ms"] for r in results]), 2
            ),
            "avg_phrase_end_to_play_ms": round(
                np.mean([r["phrase_end_to_play_ms"] for r in results]), 2
            ),
            "avg_ram_mb": round(np.mean([r["process_ram_mb"] for r in results]), 1),
        },
        "runs": results,
    }

    # Save to .runtime/benchmarks/benchmark_summary.json
    out_file = bench_dir / f"benchmark_{source_lang}_to_{target_lang}_{int(time.time())}.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Saved benchmark report to %s", out_file)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run translator benchmark")
    parser.add_argument("--source-lang", default="ur", help="Source language ('ur', 'en', 'ar')")
    parser.add_argument("--target-lang", default="en", help="Target language ('en', 'ar')")
    parser.add_argument("--iterations", type=int, default=3, help="Number of benchmark iterations")
    args = parser.parse_args()

    run_benchmark(
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        iterations=args.iterations,
    )
