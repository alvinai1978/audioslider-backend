import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from license_manager import assert_and_increment, parse_license, get_usage, license_required
from normalizer import normalize_for_speech, remove_narrator_labels
from pptx_reader import extract_slides_from_pptx, generate_commentary, split_script_by_slide
from sync_pptx import build_cloud_synced_pptx, create_timing_manifest_csv
from tts_engine import BLESSICA, ANGELO, synthesize_to_mp3

APP_NAME = "SlideNarrate Pro Full Web Cloud Backend"
WORK_DIR = Path(os.environ.get("SLIDENARRATE_WORK_DIR", tempfile.gettempdir())) / "slidenarrate_full_web"
WORK_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_NAME, version="1.2.2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", os.environ.get("ALLOWED_ORIGINS", "*")).split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-SlideNarrate-Engine", "X-SlideNarrate-Voice", "X-SlideNarrate-Duration"],
)


class TTSRequest(BaseModel):
    script: str = Field(min_length=1, max_length=120_000)
    narrator: Literal["female", "male"] = "female"
    normalize: bool = True
    language: Literal["tagalog", "english"] = "tagalog"


class NormalizeRequest(BaseModel):
    script: str = Field(min_length=1, max_length=120_000)
    language: Literal["tagalog", "english"] = "tagalog"


class LicenseCheckRequest(BaseModel):
    license_key: str


@app.get("/")
def root():
    return {"ok": True, "app": APP_NAME, "docs": "/docs"}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": APP_NAME,
        "version": "1.2.2",
        "voices": {"female": BLESSICA, "male": ANGELO},
        "features": ["generate-script", "english-script", "tagalog-script", "mp3", "synced-package", "license", "usage"],
        "license_required": license_required(),
    }


@app.post("/api/license/check")
def check_license(req: LicenseCheckRequest):
    try:
        payload = parse_license(req.license_key)
        usage = get_usage(req.license_key)
        return {"ok": True, "license": payload, "usage": usage}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/normalize")
def normalize(req: NormalizeRequest):
    return {"ok": True, "text": normalize_for_speech(req.script) if req.language == "tagalog" else remove_narrator_labels(req.script)}


@app.post("/api/generate-script")
async def generate_script(
    file: UploadFile = File(...),
    narrator: Literal["female", "male"] = Form("female"),
    style: str = Form("professional"),
    output_language: Literal["tagalog", "english"] = Form("tagalog"),
    x_slidenarrate_license: str | None = Header(default=None),
):
    try:
        assert_and_increment(x_slidenarrate_license, "script")
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    _validate_extension(file.filename, ".pptx")
    saved = await _save_upload(file, suffix=".pptx")
    try:
        slides = extract_slides_from_pptx(saved)
        script = generate_commentary(slides, narrator=narrator, style=style, output_language=output_language)
        return {"ok": True, "slide_count": len(slides), "slides": slides, "script": script, "output_language": output_language}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Script generation failed: {exc}")
    finally:
        _safe_unlink(saved)


@app.post("/api/tts")
async def tts(req: TTSRequest, x_slidenarrate_license: str | None = Header(default=None)):
    try:
        usage = assert_and_increment(x_slidenarrate_license, "mp3")
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    out_path = WORK_DIR / f"narration_{uuid.uuid4().hex}.mp3"
    try:
        meta = await synthesize_to_mp3(req.script, req.narrator, out_path, normalize=req.normalize, language=req.language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS failed: {exc}")

    headers = {
        "X-SlideNarrate-Engine": meta.get("engine", "unknown"),
        "X-SlideNarrate-Voice": meta.get("voice", "unknown"),
        "X-SlideNarrate-Duration": str(round(float(meta.get("duration", 0)), 2)),
        "Content-Disposition": 'attachment; filename="slidenarrate-narration.mp3"',
    }
    return FileResponse(str(out_path), media_type="audio/mpeg", filename="slidenarrate-narration.mp3", headers=headers)


@app.post("/api/synced-package")
async def synced_package(
    file: UploadFile = File(...),
    script: str = Form(...),
    narrator: Literal["female", "male"] = Form("female"),
    language: Literal["tagalog", "english"] = Form("tagalog"),
    x_slidenarrate_license: str | None = Header(default=None),
):
    try:
        usage = assert_and_increment(x_slidenarrate_license, "sync")
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    _validate_extension(file.filename, ".pptx")
    source_pptx = await _save_upload(file, suffix=".pptx")
    job_dir = WORK_DIR / f"sync_{uuid.uuid4().hex}"
    job_dir.mkdir(parents=True, exist_ok=True)
    zip_path = WORK_DIR / f"slidenarrate_synced_package_{uuid.uuid4().hex}.zip"

    try:
        slides = extract_slides_from_pptx(source_pptx)
        slide_count = len(slides)
        blocks = split_script_by_slide(script, slide_count)

        slide_audio_files: dict[int, Path] = {}
        durations: dict[int, float] = {}
        slide_audio_meta: dict[int, dict] = {}
        scripts_txt = []
        for n in range(1, slide_count + 1):
            text = blocks.get(n, "").strip() or f"Sa slide {n}, ipagpatuloy natin ang presentation."
            audio_path = job_dir / f"slide_{n:03d}.mp3"
            meta = await synthesize_to_mp3(text, narrator, audio_path, normalize=True, language=language)
            slide_audio_files[n] = audio_path
            durations[n] = float(meta.get("duration", 3.0))
            slide_audio_meta[n] = {**meta, "filename": f"audio/slide_{n:03d}.mp3"}
            scripts_txt.append(f"SLIDE {n}\n{text}\n")

        manifest_path = job_dir / "timing_manifest.csv"
        create_timing_manifest_csv(slide_audio_meta, manifest_path)

        synced_pptx = job_dir / "slidenarrate_cloud_synced_repaired.pptx"
        build_cloud_synced_pptx(source_pptx, synced_pptx, slide_audio_files, durations)

        readme = _package_readme(slide_count)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(synced_pptx, "slidenarrate_cloud_synced_repaired.pptx")
            z.write(source_pptx, "original_uploaded_presentation.pptx")
            z.write(manifest_path, "timing_manifest.csv")
            z.writestr("slide_scripts.txt", "\n".join(scripts_txt))
            z.writestr("README_OPEN_THIS.txt", readme)
            for n, audio_path in slide_audio_files.items():
                z.write(audio_path, f"audio/slide_{n:03d}.mp3")
        return FileResponse(str(zip_path), media_type="application/zip", filename="slidenarrate_synced_package.zip")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Synced package failed: {exc}")
    finally:
        _safe_unlink(source_pptx)


def _package_readme(slide_count: int) -> str:
    return f"""SlideNarrate Pro Synced Package v1.2.2

Files included:
- slidenarrate_cloud_synced_repaired.pptx
- original_uploaded_presentation.pptx
- audio/slide_001.mp3 ... per-slide audio files
- timing_manifest.csv
- slide_scripts.txt

How to test:
1. Extract this ZIP first. Do not open the PPTX directly inside the ZIP preview.
2. Open slidenarrate_cloud_synced_repaired.pptx in Microsoft PowerPoint Desktop.
3. If PowerPoint asks to enable media/content, allow it.
4. Press F5.

If PowerPoint still says it cannot read the repaired PPTX:
1. Use original_uploaded_presentation.pptx instead.
2. Use the included audio/slide_001.mp3, slide_002.mp3, etc.
3. For guaranteed F5 automation, import this package into the Desktop EXE version because desktop PowerPoint automation is more reliable than cloud Open XML media timing.

What changed in v1.2.2:
- Fixed an invalid PNG placeholder icon that could corrupt the exported PPTX.
- Fixed PowerPoint XML ordering for transition/timing tags.
- Removed an empty hyperlink relationship from the audio icon.
- Added the original presentation as a safe fallback.
- Added English/Tagalog output language support and buyer license enforcement.

Notes:
- Cloud synced PPTX generation is still best-effort because PowerPoint autoplay media XML varies across Office versions.
- The per-slide MP3 files are the reliable output.

Slides processed: {slide_count}
"""


def _validate_extension(filename: str | None, ext: str):
    if not filename or not filename.lower().endswith(ext):
        raise HTTPException(status_code=400, detail=f"Please upload a {ext} file.")


async def _save_upload(file: UploadFile, suffix: str) -> Path:
    out = WORK_DIR / f"upload_{uuid.uuid4().hex}{suffix}"
    data = await file.read()
    out.write_bytes(data)
    return out


def _safe_unlink(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
