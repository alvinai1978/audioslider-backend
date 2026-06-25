import asyncio
import os
from pathlib import Path
from typing import Optional

import edge_tts
from gtts import gTTS
from mutagen.mp3 import MP3

from normalizer import normalize_for_speech

BLESSICA = "fil-PH-BlessicaNeural"
ANGELO = "fil-PH-AngeloNeural"


def voice_for(narrator: str) -> str:
    return ANGELO if (narrator or "female").lower() == "male" else BLESSICA


async def synthesize_to_mp3(script: str, narrator: str, out_path: Path, normalize: bool = True) -> dict:
    text = normalize_for_speech(script) if normalize else script
    if not text.strip():
        raise ValueError("Script is empty after cleanup.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    voice = voice_for(narrator)

    errors = []
    for attempt in range(1, 3):
        try:
            await _edge_save(text, voice, out_path)
            return {"engine": "edge-tts", "voice": voice, "duration": mp3_duration(out_path)}
        except Exception as exc:
            errors.append(f"edge attempt {attempt}: {type(exc).__name__}: {exc}")
            await asyncio.sleep(1.5 * attempt)

    try:
        _gtts_save(text, out_path)
        return {"engine": "gTTS-fallback", "voice": "tl", "duration": mp3_duration(out_path), "edge_errors": errors}
    except Exception as exc:
        errors.append(f"gTTS fallback: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors))


async def _edge_save(text: str, voice: str, out_path: Path):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=os.environ.get("EDGE_TTS_RATE", "+0%"), volume="+0%")
    await communicate.save(str(out_path))


def _gtts_save(text: str, out_path: Path):
    tts = gTTS(text=text, lang="tl", slow=False)
    tts.save(str(out_path))


def mp3_duration(path: Path) -> float:
    try:
        return float(MP3(str(path)).info.length)
    except Exception:
        # fallback estimate: average Filipino speech around 145 wpm
        return max(3.0, len(path.read_bytes()) / 16000.0)
