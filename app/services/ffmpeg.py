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
from pathlib import Path
from typing import List, Optional, Tuple

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


def parse_resolution(resolution: str) -> Tuple[int, int]:
    """Parse a WxH resolution string into integers."""
    try:
        width_str, height_str = resolution.lower().split("x", 1)
        return int(width_str), int(height_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid resolution: {resolution}") from exc


def parse_color_list(colors: Optional[str]) -> List[str]:
    """Parse a comma-separated list of colors into clean entries."""
    if not colors:
        return []
    parts = [item.strip() for item in colors.replace("|", ",").split(",")]
    return [item for item in parts if item]


def build_filter_chain(
    style: str,
    resolution: str,
    fps: int,
    color: str,
    mode: str,
    colors: Optional[str] = None,
    background_color: Optional[str] = None,
    cover_image: Optional[Path] = None,
    start: Optional[float] = None,
    duration: Optional[float] = None,
    normalize: bool = False,
) -> (str, List[str]):
    """Build the FFmpeg filter_complex string and input specification.

    Parameters
    ----------
    style: 'wave', 'spectrum', 'ripple', or 'siri'
        Chooses between showwaves, showspectrum, or more stylized variants.
    resolution: e.g. '1280x720'
        Output video resolution.
    fps: frames per second for the output video.
    color: hex or named color for waveform (for wave/ripple).
    mode: one of showwaves modes (point, line, p2p, cline) when style='wave'.
    colors: comma-separated list of colors for multi-layer styles (siri).
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

    width, height = parse_resolution(resolution)
    filters: List[str] = []
    fg_label = "fg"
    overlay_expr = "overlay=format=auto:shortest=1"

    if style in {"wave", "spectrum", "ripple"}:
        audio_chain: List[str] = []
        if normalize:
            audio_chain.append("loudnorm")
        if style == "wave":
            wave_opts = [f"s={resolution}", f"mode={mode}", f"rate={fps}"]
            if color:
                wave_opts.append(f"colors={color}")
            audio_chain.append(f"showwaves={':'.join(wave_opts)}")
        elif style == "spectrum":
            spec_opts = [
                f"s={resolution}",
                "mode=combined",
                "color=intensity",
                "slide=scroll",
                "win_func=hann",
                "rotation=0",
            ]
            audio_chain.append(f"showspectrum={':'.join(spec_opts)}")
        elif style == "ripple":
            square_size = min(width, height)
            ripple_resolution = f"{square_size}x{square_size}"
            wave_opts = [f"s={ripple_resolution}", "mode=cline", f"rate={fps}"]
            if color:
                wave_opts.append(f"colors={color}")
            audio_chain.append(f"showwaves={':'.join(wave_opts)}")
            audio_chain.append("format=rgba")
            audio_chain.append(f"v360=input=rectilinear:output=ball:w={square_size}:h={square_size}")
            audio_chain.append("gblur=sigma=2")
            overlay_expr = "overlay=x=(W-w)/2:y=(H-h)/2:format=auto:shortest=1"
        audio_filter = ",".join(audio_chain)
        filters.append(f"[0:a]{audio_filter}[{fg_label}]")
    elif style == "siri":
        palette = parse_color_list(colors)
        if not palette:
            palette = ["#3b82f6", "#22c55e", "#f97316", "#ec4899"]
        palette = palette[:4]
        split_labels = [f"a{i}" for i in range(len(palette))]
        split_chain = "loudnorm," if normalize else ""
        splits = "".join(f"[{label}]" for label in split_labels)
        filters.append(f"[0:a]{split_chain}asplit={len(palette)}{splits}")
        wave_labels = []
        for idx, color_item in enumerate(palette):
            wave_label = f"w{idx}"
            wave_opts = [f"s={resolution}", "mode=cline", f"rate={fps}", f"colors={color_item}"]
            filters.append(
                f"[{split_labels[idx]}]showwaves={':'.join(wave_opts)},"
                "format=rgba,colorchannelmixer=aa=0.7,gblur=sigma=1.5"
                f"[{wave_label}]"
            )
            wave_labels.append(wave_label)
        current = wave_labels[0]
        for idx in range(1, len(wave_labels)):
            mixed = f"mix{idx}"
            filters.append(f"[{current}][{wave_labels[idx]}]overlay=format=auto:shortest=1[{mixed}]")
            current = mixed
        fg_label = current
    else:
        raise HTTPException(status_code=400, detail="Unknown style")

    # Build background: either static colour or cover image
    if cover_image:
        # Use input 1 (image) scaled to desired resolution
        filters.append(f"[1:v]scale={resolution}[bg]")
    else:
        # Use colour filter as background
        # Create a coloured image of the same duration using the color source
        # See https://ffmpeg.org/ffmpeg-filters.html#color-source
        filters.append(f"color=c={background_color or 'black'}:s={resolution}:r={fps}[bg]")
    # Overlay the foreground (wave) onto the background
    # Use format=auto to ensure proper pixel format negotiation
    filters.append(f"[bg][{fg_label}]{overlay_expr}[outv]")
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
    colors: Optional[str] = None,
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
    style, resolution, fps, color, mode, colors, background_color, cover_image,
    start, duration, normalize: rendering options.
    """
    # Build the filter graph and additional inputs
    filter_complex, extra_inputs = build_filter_chain(
        style=style,
        resolution=resolution,
        fps=fps,
        color=color,
        mode=mode,
        colors=colors,
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
