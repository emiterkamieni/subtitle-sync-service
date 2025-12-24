# Subtitle Sync Service

🎬 **FastAPI microservice for automatic subtitle synchronization**

This service synchronizes subtitles with video streams using audio analysis.
Designed for use with CinemaVOD Android TV application.

## How it works

1. **Audio Extraction**: Downloads first 5 minutes of audio from video stream
2. **Analysis**: Uses `alass` (fast subtitle aligner) to detect speech patterns
3. **Synchronization**: Calculates offset and shifts subtitle timestamps
4. **Response**: Returns offset in milliseconds and/or synced subtitle

## API Endpoints

### `GET /` - Health check
Returns service status.

### `GET /health` - Detailed health
Checks if FFmpeg and alass are available.

### `POST /sync` - Full sync
Synchronizes subtitle with video stream.

**Request:**
```json
{
  "stream_url": "https://example.com/video.mp4",
  "subtitle": "1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n...",
  "language": "en"
}
```

**Response:**
```json
{
  "success": true,
  "offset_ms": -1500,
  "synced_subtitle": "1\n00:00:02,500 --> 00:00:05,500\nHello world\n\n...",
  "confidence": 0.92,
  "message": "Synchronized successfully. Offset: -1500ms",
  "processing_time_ms": 12500
}
```

### `POST /offset` - Offset only
Same as `/sync` but returns only the offset, not full subtitle (lighter response).

## Deployment on Render.com (FREE)

### Step 1: Create GitHub Repository

```bash
cd subtitle-sync-service
git init
git add .
git commit -m "Initial commit: Subtitle Sync Service"
git remote add origin https://github.com/YOUR_USERNAME/subtitle-sync-service.git
git push -u origin main
```

### Step 2: Deploy to Render.com

1. Go to [render.com](https://render.com) and sign up (free)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Render will auto-detect `render.yaml` and configure everything
5. Click **"Create Web Service"**
6. Wait ~5 minutes for build and deploy

### Step 3: Get your service URL

After deployment, you'll get a URL like:
```
https://subtitle-sync-service.onrender.com
```

## Limitations (Free Tier)

- **Spin-down**: Service sleeps after 15 min of inactivity
- **Cold start**: First request after sleep takes ~30-60 seconds
- **RAM**: 512MB limit
- **CPU**: Shared CPU
- **Build time**: 750 free hours/month

## Integration with CinemaVOD

Add to your Android app's `local.properties`:
```
SYNC_SERVICE_URL=https://your-service.onrender.com
```

## Local Development

```bash
# Build and run with Docker
docker build -t subtitle-sync .
docker run -p 8000:8000 subtitle-sync

# Or run directly with Python
pip install -r requirements.txt
python main.py
```

## License

MIT License
