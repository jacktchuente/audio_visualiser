"""
This module provides helper functions for building and executing FFmpeg
commands to generate waveform or spectrum visualisations from audio files.

The key entry point is `render_visualization`, which takes an input
audio file and optional cover image along with rendering parameters and
writes the result to the specified output path. The command is
constructed safely without invoking a shell.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException


async def run_command(cmd: List[str]) -> None:
    """Run a command asynchronously and raise on non‑zero exit status.

    The command is executed without a shell to avoid injection issues.
    Standard output and error are captured and logged to provide
    troubleshooting information if the command fails. If the return
    code is non‑zero, an HTTPException is raised with the stderr
    captured from the process.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise HTTPException(status_code=500, detail=f"FFmpeg failed: {err}")


async def get_audio_duration(input_path: Path) -> float:
    """Return the duration of the audio file in seconds using ffprobe.

    This function runs ffprobe to extract the duration. If ffprobe is
    missing or fails, an exception is raised.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"ffprobe failed to read duration: {stderr.decode().strip()}",
        )
    try:
        return float(stdout.decode().strip())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid duration returned by ffprobe") from exc


def build_filter_chain(
    style: str,
    resolution: str,
    fps: int,
    color: str,
    mode: str,
    background_color: Optional[str] = None,
    cover_image: Optional[Path] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    normalize: bool = False,
) -> (str, List[str]):
    """Build the FFmpeg filter_complex string and input specification.

    Parameters
    ----------
    style: 'wave' or 'spectrum'
        Chooses between showwaves or showspectrum.
    resolution: e.g. '1280x720'
        Output video resolution.
    fps: frames per second for the output video.
    color: hex or named color for waveform/spectrum (for wave mode only).
    mode: one of showwaves modes (point, line, p2p, cline) when style='wave'.
    background_color: hex or named background colour if no cover image.
    cover_image: optional image file to use as background.
    start: optional start time offset (seconds) to trim input audio.
    duration: optional maximum duration to render (seconds).
    normalize: whether to apply loudness normalization before visualising.

    Returns
    -------
    filter_complex: FFmpeg filter graph string.
    inputs: additional input arguments to supply before filter_complex.
    """
    # Input streams labels: audio is always input 0. If cover image is provided it
    # becomes input 1 and we set it to loop.
    inputs: List[str] = []
    if cover_image:
        # For static images we use -loop 1 so the frame repeats for the entire
        # duration of the audio. Add the image input after the audio.
        inputs.extend(["-loop", "1", "-i", str(cover_image)])

    filters = []
    audio_chain = []
    # Optionally normalise loudness
    if normalize:
        audio_chain.append("loudnorm")
    # Build the visual filter depending on style
    if style == "wave":
        # showwaves filter; set size, mode and colours. We rely on the
        # 'colors' option for colour selection and 'mode' for waveform drawing.
        wave_opts = [f"s={resolution}", f"mode={mode}", f"rate={fps}"]
        if color:
            wave_opts.append(f"colors={color}")
        audio_chain.append(f"showwaves={':'.join(wave_opts)}")
    elif style == "spectrum":
        # showspectrum filter; we use combined mode and intensity colour scale.
        # The 'color' option isn't honoured in showspectrum; we keep intensity.
        spec_opts = [f"s={resolution}", "mode=combined", "color=intensity", f"slide=scroll", f"win_func=hann", f"rotation=0"]
        audio_chain.append(f"showspectrum={':'.join(spec_opts)}")
    else:
        raise HTTPException(status_code=400, detail="Unknown style")
    # Chain audio filters
    audio_filter = ",".join(audio_chain)
    # Label the audio visual output as [fg]
    audio_filter_label = f"[0:a]{audio_filter}[fg]"
    # Build background: either static colour or cover image
    if cover_image:
        # Use input 1 (image) scaled to desired resolution
        filters.append(f"[1:v]scale={resolution}[bg]")
    else:
        # Use colour filter as background
        # Create a coloured image of the same duration using the color source
        # See https://ffmpeg.org/ffmpeg-filters.html#color-source
        filters.append(f"color=c={background_color or 'black'}:s={resolution}:r={fps}[bg]")
    # Append the waveform chain
    filters.append(audio_filter_label)
    # Overlay the foreground (wave) onto the background
    # Use format=auto to ensure proper pixel format negotiation
    filters.append("[bg][fg]overlay=format=auto:shortest=1[outv]")
    # Combine filter_complex
    filter_complex = ";".join(filters)
    return filter_complex, inputs


async def render_visualization(
    input_audio: Path,
    output_video: Path,
    *,
    style: str = "wave",
    resolution: str = "1280x720",
    fps: int = 25,
    color: str = "white",
    mode: str = "line",
    background_color: str = "black",
    cover_image: Optional[Path] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    normalize: bool = False,
) -> None:
    """Render an audio visualisation to a video file using FFmpeg.

    Parameters
    ----------
    input_audio: path to the audio file.
    output_video: path to write the resulting video.
    style, resolution, fps, color, mode, background_color, cover_image,
    start, duration, normalize: rendering options.
    """
    # Build the filter graph and additional inputs
    filter_complex, extra_inputs = build_filter_chain(
        style=style,
        resolution=resolution,
        fps=fps,
        color=color,
        mode=mode,
        background_color=background_color,
        cover_image=cover_image,
        start=start,
        duration=duration,
        normalize=normalize,
    )
    # Build command arguments
    cmd: List[str] = ["ffmpeg", "-y"]
    # Input audio
    cmd += ["-i", str(input_audio)]
    # Insert cover image if needed
    cmd += extra_inputs
    # Optional trimming; use -ss and -t on the input after specifying inputs
    if start is not None:
        cmd += ["-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    # Add filter_complex
    cmd += ["-filter_complex", filter_complex]
    # Map the output video and audio
    cmd += ["-map", "[outv]", "-map", "0:a"]
    # Encode using H.264 and AAC
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [str(output_video)]
    # Run command
    await run_command(cmd)
