#!/usr/bin/env python3
"""Transcribe a system design walkthrough recording to text.

Extracts audio with ffmpeg, then runs whisper.cpp (large-v3) on the Apple GPU
via Metal, with Silero VAD to trim silence and suppress hallucination on
long pauses.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = REPO_ROOT / "recordings"
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
MODELS_DIR = REPO_ROOT / "models"
DEFAULT_VAD_MODEL = MODELS_DIR / "ggml-silero-v6.2.0.bin"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a"}


def newest_recording() -> Path:
    candidates = [
        p
        for p in RECORDINGS_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
    ]
    if not candidates:
        sys.exit(
            f"No recordings found in {RECORDINGS_DIR}. "
            "Drop a video there or pass a path explicitly."
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def extract_audio(video: Path, wav_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it with: brew install ffmpeg")
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            "-i", str(video),
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            "-y", str(wav_path),
        ],
        check=True,
    )


def format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def run_whisper_cli(
    wav_path: Path,
    model_path: Path,
    vad_model: Path,
    language: str,
    beam_size: int,
    out_prefix: Path,
    max_context=None,
) -> Path:
    binary = shutil.which("whisper-cli")
    if binary is None:
        sys.exit("whisper-cli not found on PATH. Install it with: brew install whisper-cpp")
    if not model_path.is_file():
        sys.exit(
            f"Model not found: {model_path}\nDownload it with:\n"
            f"  curl -fL --progress-bar -o {model_path} "
            f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{model_path.name}"
        )
    if not vad_model.is_file():
        sys.exit(
            f"VAD model not found: {vad_model}\nDownload it with:\n"
            f"  curl -fL --progress-bar -o {vad_model} "
            f"https://huggingface.co/ggml-org/whisper-vad/resolve/main/{vad_model.name}"
        )

    command = [
        binary,
        "-m", str(model_path),
        "-f", str(wav_path),
        "-l", language,
        "-bs", str(beam_size),
    ]
    if max_context is not None:
        command.extend(["-mc", str(max_context)])
    command.extend([
        "--vad",
        "-vm", str(vad_model),
        "-oj",
        "-of", str(out_prefix),
    ])

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    # whisper-cli streams timestamped segments to stdout; mirror them as progress.
    for line in process.stdout:
        line = line.rstrip()
        if line:
            print(f"  {line}", file=sys.stderr)
    if process.wait() != 0:
        sys.exit(f"whisper-cli failed with exit code {process.returncode}")

    json_path = out_prefix.with_name(out_prefix.name + ".json")
    if not json_path.is_file():
        sys.exit(f"whisper-cli produced no JSON at {json_path}")
    return json_path


def parse_segments(json_path: Path) -> list[str]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    lines = []
    for segment in data.get("transcription", []):
        text = segment.get("text", "").strip()
        if text:
            start = segment["offsets"]["from"] / 1000.0
            lines.append(f"[{format_timestamp(start)}] {text}")
    return lines


def has_repetition_loop(
    lines: list[str],
    phrase_words: int = 6,
    consecutive_segments: int = 8,
) -> bool:
    active_runs = {}
    for line in lines:
        text = line.partition("] ")[2]
        words = re.findall(r"[a-z0-9]+", text.lower())
        phrases = {
            tuple(words[index:index + phrase_words])
            for index in range(len(words) - phrase_words + 1)
        }
        active_runs = {
            phrase: active_runs.get(phrase, 0) + 1
            for phrase in phrases
        }
        if any(run >= consecutive_segments for run in active_runs.values()):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "video",
        nargs="?",
        type=Path,
        help="Path to the recording. Defaults to the newest file in recordings/.",
    )
    parser.add_argument("--model", default="large-v3", help="Whisper model size.")
    parser.add_argument("--language", default="en", help="Spoken language.")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam search width.")
    parser.add_argument(
        "--vad-model",
        type=Path,
        default=DEFAULT_VAD_MODEL,
        help="Path to the Silero VAD ggml model.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="FILE",
        help="Full output file path. Defaults to transcripts/<stem>_<stamp>.txt.",
    )
    args = parser.parse_args()

    video = args.video.expanduser().resolve() if args.video else newest_recording()
    if not video.is_file():
        sys.exit(f"Not a file: {video}")

    if args.out:
        output = args.out.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
    else:
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        output = TRANSCRIPTS_DIR / f"{video.stem}_{stamp}.txt"

    print(f"Source:  {video}", file=sys.stderr)
    started = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        print("Extracting audio...", file=sys.stderr)
        extract_audio(video, wav_path)
        audio_seconds = wav_duration(wav_path)

        print(f"Transcribing with whisper.cpp '{args.model}' (Metal)...", file=sys.stderr)
        json_path = run_whisper_cli(
            wav_path=wav_path,
            model_path=MODELS_DIR / f"ggml-{args.model}.bin",
            vad_model=args.vad_model.expanduser(),
            language=args.language,
            beam_size=args.beam_size,
            out_prefix=Path(tmpdir) / "result",
        )
        lines = parse_segments(json_path)
        if has_repetition_loop(lines):
            print(
                "Detected a repeated transcription loop; retrying without retained text context...",
                file=sys.stderr,
            )
            json_path = run_whisper_cli(
                wav_path=wav_path,
                model_path=MODELS_DIR / f"ggml-{args.model}.bin",
                vad_model=args.vad_model.expanduser(),
                language=args.language,
                beam_size=args.beam_size,
                out_prefix=Path(tmpdir) / "retry",
                max_context=0,
            )
            lines = parse_segments(json_path)
            if has_repetition_loop(lines):
                sys.exit("Transcription remained stuck in a repeated phrase after retrying.")

    if not lines:
        sys.exit("Transcription produced no text. Check that the recording has audio.")

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    elapsed = time.monotonic() - started
    word_count = sum(len(line.split()) for line in lines)
    rtf = elapsed / audio_seconds if audio_seconds else float("nan")
    print(f"\nDuration: {format_timestamp(audio_seconds)}", file=sys.stderr)
    print(f"Words:    {word_count}", file=sys.stderr)
    print(f"Elapsed:  {elapsed:.1f}s (RTF {rtf:.3f})", file=sys.stderr)
    print(f"Wrote:    {output}", file=sys.stderr)
    print(output)


if __name__ == "__main__":
    main()
