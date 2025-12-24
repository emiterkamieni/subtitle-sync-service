"""
Subtitle Sync Service
=====================
A FastAPI microservice that synchronizes subtitles with video streams.

How it works:
1. Receives stream URL and subtitle content
2. Downloads first 5 minutes of audio using FFmpeg
3. Runs alass to calculate sync offset
4. Returns synchronized subtitle or offset

Deploy to: Render.com (Free Tier)
"""

import os
import tempfile
import subprocess
import re
import hashlib
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(
    title="Subtitle Sync Service",
    description="Synchronize subtitles with video streams using audio analysis",
    version="1.0.0"
)

# CORS for app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
AUDIO_DURATION = 300  # 5 minutes of audio for analysis
CACHE_DIR = "/tmp/sync_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


class SyncRequest(BaseModel):
    """Request body for sync endpoint"""
    stream_url: str  # URL of the video stream
    subtitle: str    # SRT subtitle content
    language: str = "en"  # Subtitle language


class SyncResponse(BaseModel):
    """Response from sync endpoint"""
    success: bool
    offset_ms: int  # Calculated offset in milliseconds
    synced_subtitle: Optional[str] = None  # Synchronized SRT content
    confidence: Optional[float] = None
    message: str
    processing_time_ms: int


def parse_srt_time(time_str: str) -> int:
    """Parse SRT timestamp to milliseconds"""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if not match:
        return 0
    h, m, s, ms = map(int, match.groups())
    return h * 3600000 + m * 60000 + s * 1000 + ms


def ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp"""
    if ms < 0:
        ms = 0
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def shift_srt(srt_content: str, offset_ms: int) -> str:
    """Shift all timestamps in SRT by offset_ms"""
    time_pattern = re.compile(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})')
    
    def replace_times(match):
        start = parse_srt_time(match.group(1))
        end = parse_srt_time(match.group(2))
        new_start = ms_to_srt_time(start + offset_ms)
        new_end = ms_to_srt_time(end + offset_ms)
        return f"{new_start} --> {new_end}"
    
    return time_pattern.sub(replace_times, srt_content)


def extract_audio(stream_url: str, output_path: str, duration: int = AUDIO_DURATION) -> bool:
    """
    Extract audio from stream URL using FFmpeg.
    Only downloads first N seconds to minimize bandwidth.
    """
    try:
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite
            "-t", str(duration),  # Duration limit
            "-i", stream_url,
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # WAV format for alass
            "-ar", "16000",  # 16kHz sample rate (sufficient for speech)
            "-ac", "1",  # Mono
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120  # 2 minute timeout
        )
        
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"FFmpeg error: {e}")
        return False


def run_alass_sync(audio_path: str, subtitle_path: str, output_path: str) -> tuple[bool, float]:
    """
    Run alass to synchronize subtitle with audio.
    Returns (success, confidence_score)
    """
    try:
        cmd = [
            "alass",
            audio_path,
            subtitle_path,
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Parse alass output for confidence
        confidence = 0.0
        if "score:" in result.stdout.lower():
            match = re.search(r'score:\s*([\d.]+)', result.stdout.lower())
            if match:
                confidence = float(match.group(1))
        
        success = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        return success, confidence
        
    except subprocess.TimeoutExpired:
        print("alass timeout")
        return False, 0.0
    except Exception as e:
        print(f"alass error: {e}")
        return False, 0.0


def calculate_offset_from_srt(original: str, synced: str) -> int:
    """Calculate offset by comparing first subtitle timing"""
    orig_match = re.search(r'(\d{2}:\d{2}:\d{2},\d{3}) -->', original)
    sync_match = re.search(r'(\d{2}:\d{2}:\d{2},\d{3}) -->', synced)
    
    if orig_match and sync_match:
        orig_ms = parse_srt_time(orig_match.group(1))
        sync_ms = parse_srt_time(sync_match.group(1))
        return sync_ms - orig_ms
    
    return 0


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Subtitle Sync Service",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Health check for monitoring"""
    # Check if ffmpeg and alass are available
    ffmpeg_ok = subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    alass_ok = subprocess.run(["alass", "--version"], capture_output=True).returncode == 0
    
    return {
        "status": "healthy" if (ffmpeg_ok and alass_ok) else "degraded",
        "ffmpeg": "ok" if ffmpeg_ok else "missing",
        "alass": "ok" if alass_ok else "missing"
    }


@app.post("/sync", response_model=SyncResponse)
async def sync_subtitle(request: SyncRequest):
    """
    Synchronize subtitle with video stream.
    
    This endpoint:
    1. Downloads first 5 minutes of audio from the stream
    2. Uses alass to align subtitle with audio
    3. Returns the offset and/or synchronized subtitle
    """
    start_time = datetime.now()
    
    # Create unique hash for caching
    url_hash = hashlib.md5(request.stream_url.encode()).hexdigest()[:8]
    sub_hash = hashlib.md5(request.subtitle.encode()).hexdigest()[:8]
    cache_key = f"{url_hash}_{sub_hash}"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.wav")
        sub_path = os.path.join(tmpdir, "input.srt")
        synced_path = os.path.join(tmpdir, "synced.srt")
        
        # Save subtitle to file
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(request.subtitle)
        
        # Extract audio from stream
        if not extract_audio(request.stream_url, audio_path):
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return SyncResponse(
                success=False,
                offset_ms=0,
                message="Failed to extract audio from stream",
                processing_time_ms=processing_time
            )
        
        # Run alass sync
        success, confidence = run_alass_sync(audio_path, sub_path, synced_path)
        
        if not success:
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return SyncResponse(
                success=False,
                offset_ms=0,
                message="Synchronization failed",
                processing_time_ms=processing_time
            )
        
        # Read synced subtitle
        with open(synced_path, "r", encoding="utf-8") as f:
            synced_content = f.read()
        
        # Calculate offset
        offset_ms = calculate_offset_from_srt(request.subtitle, synced_content)
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return SyncResponse(
            success=True,
            offset_ms=offset_ms,
            synced_subtitle=synced_content,
            confidence=confidence,
            message=f"Synchronized successfully. Offset: {offset_ms}ms",
            processing_time_ms=processing_time
        )


@app.post("/offset", response_model=SyncResponse)
async def get_offset_only(request: SyncRequest):
    """
    Calculate sync offset without returning full subtitle.
    Lighter endpoint for mobile apps.
    """
    response = await sync_subtitle(request)
    # Clear the full subtitle to reduce response size
    response.synced_subtitle = None
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
