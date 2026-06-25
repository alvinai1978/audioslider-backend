import asyncio
import os
from pathlib import Path

import edge_tts
from gtts import gTTS
from mutagen.mp3 import MP3

from normalizer import normalize_for_speech, remove_narrator_labels

BLESSICA = "fil-PH-BlessicaNeural"
ANGELO = "fil-PH-AngeloNeural"
ENGLISH_FEMALE = "en-US-JennyNeural"
ENGLISH_MALE = "en-US-GuyNeural"


def voice_for(narrator: str, language: str = "tagalog") -> str:
    lang = (language or "tagalog").lower()
    if lang.startswith("en"):
        return ENGLISH_MALE if (narrator or "female").lower() == "male" else ENGLISH_FEMALE
    return ANGELO if (narrator or "female").lower() == "male" else BLESSICA


def clean_text_for_tts(script: str, normalize: bool = True, language: str = "tagalog") -> str:
    lang = (language or "tagalog").lower()
    if not normalize:
        return remove_narrator_labels(script or "")
    if lang.startswith("en"):
        return remove_narrator_labels(script or "")
    return normalize_for_speech(script or "")


async def synthesize_to_mp3(script: str, narrator: str, out_path: Path, normalize: bool = True, language: str = "tagalog") -> dict:
    text = clean_text_for_tts(script, normalize=normalize, language=language)
    if not text.strip():
        raise ValueError("Script is empty after cleanup.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lang = (language or "tagalog").lower()
    voice = voice_for(narrator, language=lang)

    errors = []
    for attempt in range(1, 3):
        try:
            await _edge_save(text, voice, out_path)
            return {"engine": "edge-tts", "voice": voice, "duration": mp3_duration(out_path), "language": lang}
        except Exception as exc:
            errors.append(f"edge attempt {attempt}: {type(exc).__name__}: {exc}")
            await asyncio.sleep(1.5 * attempt)

    try:
        _gtts_save(text, out_path, language=lang)
        return {"engine": "gTTS-fallback", "voice": "en" if lang.startswith("en") else "tl", "duration": mp3_duration(out_path), "edge_errors": errors, "language": lang}
    except Exception as exc:
        errors.append(f"gTTS fallback: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors))


async def _edge_save(text: str, voice: str, out_path: Path):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=os.environ.get("EDGE_TTS_RATE", "+0%"), volume="+0%")
    await communicate.save(str(out_path))


def _gtts_save(text: str, out_path: Path, language: str = "tagalog"):
    lang = "en" if (language or "tagalog").lower().startswith("en") else "tl"
    tts = gTTS(text=text, lang=lang, slow=False)
    tts.save(str(out_path))


def mp3_duration(path: Path) -> float:
    try:
        return float(MP3(str(path)).info.length)
    except Exception:
        return max(3.0, len(path.read_bytes()) / 16000.0)
