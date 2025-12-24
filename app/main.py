"""
FastAPI entry point for the audio waveform visualiser application.

This module defines HTTP endpoints for uploading audio files,
configuring render parameters and retrieving the resulting MP4
visualisations. Jobs are processed asynchronously and clients can
poll their status or download completed outputs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    UploadFile,
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .services import ffmpeg, jobs

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
JOBS_DIR = DATA_DIR / "jobs"

# Ensure data directories exist
for d in [UPLOAD_DIR, OUTPUT_DIR, JOBS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Audio Visualiser")

# Serve static files and templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")

# Settings
MAX_UPLOAD_SIZE_MB = float(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))  # limit upload size
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


def validate_file(filename: str, allowed: set[str]) -> None:
    """Validate that file extension is allowed."""
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")


async def save_upload(file: UploadFile, dest_dir: Path) -> Path:
    """Save an uploaded file to destination directory and return the path."""
    dest_path = dest_dir / f"{jobs.uuid4().hex}{Path(file.filename).suffix}"
    # Check file size while reading
    size = 0
    with dest_path.open("wb") as fout:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                raise HTTPException(status_code=413, detail="File too large")
            fout.write(chunk)
    await file.close()
    return dest_path


@app.post("/upload", response_class=JSONResponse)
async def upload(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    cover: Optional[UploadFile] = File(None),
    # Rendering options
    style: str = Form("wave"),
    resolution: str = Form("1280x720"),
    fps: int = Form(25),
    color: str = Form("white"),
    mode: str = Form("line"),
    colors: Optional[str] = Form(None),
    background: str = Form("black"),
    normalize: bool = Form(False),
    start: Optional[float] = Form(None),
    duration: Optional[float] = Form(None),
) -> JSONResponse:
    """Handle audio upload and schedule rendering job."""
    # Validate audio file
    validate_file(audio.filename, ALLOWED_AUDIO_EXTS)
    audio_path = await save_upload(audio, UPLOAD_DIR)
    # Validate optional cover image
    cover_path: Optional[Path] = None
    if cover and cover.filename:
        validate_file(cover.filename, ALLOWED_IMAGE_EXTS)
        cover_path = await save_upload(cover, UPLOAD_DIR)

    async def task(job_id: str) -> Path:
        """Background task for rendering the video."""
        out_path = OUTPUT_DIR / f"{job_id}.mp4"
        # Invoke ffmpeg render
        await ffmpeg.render_visualization(
            audio_path,
            out_path,
            style=style,
            resolution=resolution,
            fps=fps,
            color=color,
            mode=mode,
            colors=colors,
            background_color=background,
            cover_image=cover_path,
            start=start,
            duration=duration,
            normalize=normalize,
        )
        # After successful render, remove uploaded files
        try:
            audio_path.unlink(missing_ok=True)
            if cover_path:
                cover_path.unlink(missing_ok=True)
        except Exception:
            pass
        return out_path

    job_id = jobs.create_job(task)
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/status/{job_id}", response_class=JSONResponse)
async def status(job_id: str) -> JSONResponse:
    """Return the status of a given job."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(job)


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    """Return the rendered MP4 for a completed job."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job id")
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job not completed yet")
    # Serve the file
    file_path = OUTPUT_DIR / f"{job_id}.mp4"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type="video/mp4", filename=f"{job_id}.mp4")
