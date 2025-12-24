"""
Subtitle Sync Service
=====================
A FastAPI microservice that synchronizes subtitles with video streams.

How it works:
1. Receives stream URL and subtitle content
2. Downloads first 10 minutes of audio using FFmpeg
3. Runs ffsubsync for accurate audio-based synchronization
4. Returns synchronized subtitle and offset

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
    version="1.1.0"
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
AUDIO_DURATION = 600  # 10 minutes of audio for better analysis
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


def extract_audio(stream_url: str, output_path: str, duration: int = AUDIO_DURATION) -> bool:
    """
    Extract audio from stream URL using FFmpeg.
    Only downloads first N seconds to minimize bandwidth.
    """
    try:
        print(f"[FFmpeg] Extracting {duration}s of audio from: {stream_url[:100]}...")
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite
            "-t", str(duration),  # Duration limit
            "-i", stream_url,
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # WAV format
            "-ar", "16000",  # 16kHz sample rate
            "-ac", "1",  # Mono
            "-loglevel", "warning",
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180  # 3 minute timeout
        )
        
        if result.returncode != 0:
            print(f"[FFmpeg] Error: {result.stderr.decode()}")
            return False
        
        file_exists = os.path.exists(output_path)
        file_size = os.path.getsize(output_path) if file_exists else 0
        print(f"[FFmpeg] Audio extracted: {file_exists}, size: {file_size} bytes")
        
        return file_exists and file_size > 10000
    except subprocess.TimeoutExpired:
        print("[FFmpeg] Timeout expired")
        return False
    except Exception as e:
        print(f"[FFmpeg] Exception: {e}")
        return False


def run_ffsubsync(audio_path: str, subtitle_path: str, output_path: str) -> tuple[bool, str]:
    """
    Run ffsubsync to synchronize subtitle with audio.
    Returns (success, output_log)
    """
    try:
        print(f"[ffsubsync] Starting synchronization...")
        
        cmd = [
            "ffsubsync",
            audio_path,
            "-i", subtitle_path,
            "-o", output_path,
            "--no-fix-framerate",
            "--max-offset-seconds", "60"  # Allow up to 60s offset
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        output_log = result.stdout + result.stderr
        print(f"[ffsubsync] Output: {output_log}")
        
        success = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        return success, output_log
        
    except subprocess.TimeoutExpired:
        print("[ffsubsync] Timeout")
        return False, "Timeout"
    except Exception as e:
        print(f"[ffsubsync] Exception: {e}")
        return False, str(e)


def run_alass_sync(audio_path: str, subtitle_path: str, output_path: str) -> tuple[bool, str]:
    """
    Run alass to synchronize subtitle with audio (fallback).
    Returns (success, output_log)
    """
    try:
        print(f"[alass] Starting synchronization...")
        
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
        
        output_log = result.stdout + result.stderr
        print(f"[alass] Output: {output_log}")
        
        success = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        return success, output_log
        
    except subprocess.TimeoutExpired:
        print("[alass] Timeout")
        return False, "Timeout"
    except Exception as e:
        print(f"[alass] Exception: {e}")
        return False, str(e)


def calculate_offset_from_srt(original: str, synced: str) -> int:
    """Calculate average offset by comparing multiple subtitle timings"""
    orig_times = re.findall(r'(\d{2}:\d{2}:\d{2},\d{3}) -->', original)
    sync_times = re.findall(r'(\d{2}:\d{2}:\d{2},\d{3}) -->', synced)
    
    if not orig_times or not sync_times:
        return 0
    
    # Compare first 5 subtitles for more accurate average
    offsets = []
    for i in range(min(5, len(orig_times), len(sync_times))):
        orig_ms = parse_srt_time(orig_times[i])
        sync_ms = parse_srt_time(sync_times[i])
        offsets.append(sync_ms - orig_ms)
    
    if offsets:
        # Return median offset (more robust than average)
        offsets.sort()
        return offsets[len(offsets) // 2]
    
    return 0


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Subtitle Sync Service",
        "version": "1.1.0",
        "audio_duration": AUDIO_DURATION
    }


@app.get("/health")
async def health():
    """Health check for monitoring"""
    ffmpeg_ok = subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    
    # Check for ffsubsync or alass
    try:
        ffsubsync_ok = subprocess.run(["ffsubsync", "--version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        ffsubsync_ok = False
    
    try:
        alass_ok = subprocess.run(["alass", "--version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        alass_ok = False
    
    return {
        "status": "healthy" if (ffmpeg_ok and (ffsubsync_ok or alass_ok)) else "degraded",
        "ffmpeg": "ok" if ffmpeg_ok else "missing",
        "ffsubsync": "ok" if ffsubsync_ok else "missing",
        "alass": "ok" if alass_ok else "missing"
    }


@app.post("/sync", response_model=SyncResponse)
async def sync_subtitle(request: SyncRequest):
    """
    Synchronize subtitle with video stream.
    
    This endpoint:
    1. Downloads first 10 minutes of audio from the stream
    2. Uses ffsubsync (or alass fallback) to align subtitle with audio
    3. Returns the offset and/or synchronized subtitle
    """
    start_time = datetime.now()
    print(f"\n{'='*50}")
    print(f"[SYNC] New request at {start_time}")
    print(f"[SYNC] Stream URL: {request.stream_url[:100]}...")
    print(f"[SYNC] Subtitle length: {len(request.subtitle)} chars")
    
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
                message="Failed to extract audio from stream. Check if URL is accessible.",
                processing_time_ms=processing_time
            )
        
        # Try ffsubsync first (more accurate)
        success = False
        output_log = ""
        
        try:
            success, output_log = run_ffsubsync(audio_path, sub_path, synced_path)
        except FileNotFoundError:
            print("[SYNC] ffsubsync not found, trying alass...")
        
        # Fallback to alass if ffsubsync failed
        if not success:
            print("[SYNC] Trying alass as fallback...")
            success, output_log = run_alass_sync(audio_path, sub_path, synced_path)
        
        if not success:
            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            return SyncResponse(
                success=False,
                offset_ms=0,
                message=f"Synchronization failed: {output_log[:200]}",
                processing_time_ms=processing_time
            )
        
        # Read synced subtitle
        with open(synced_path, "r", encoding="utf-8") as f:
            synced_content = f.read()
        
        # Calculate offset
        offset_ms = calculate_offset_from_srt(request.subtitle, synced_content)
        
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
        print(f"[SYNC] Success! Offset: {offset_ms}ms, Time: {processing_time}ms")
        
        return SyncResponse(
            success=True,
            offset_ms=offset_ms,
            synced_subtitle=synced_content,
            confidence=0.9,
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
