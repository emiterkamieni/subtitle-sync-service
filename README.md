# 🎬 Subtitle Sync Service

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

**FastAPI microservice for automatic subtitle synchronization with video streams.**

Uses audio analysis (speech detection) to perfectly align subtitles with video content. Designed for use with streaming applications like CinemaVOD.

## ✨ Features

- 🎵 **Audio-based sync** - Uses FFSubSync for accurate speech detection
- 🌐 **Stream support** - Works with any video URL (HLS, MP4, etc.)
- ⚡ **REST API** - Simple POST endpoint for integration
- 🔄 **Fallback support** - Uses alass as fallback if FFSubSync fails
- 📊 **Offset calculation** - Returns offset in milliseconds for easy integration

## 🔧 How it works

```
┌─────────────────────┐
│   Your App          │
│   (Android/iOS/Web) │
└──────────┬──────────┘
           │ POST /sync
           │ {stream_url, subtitle}
           ▼
┌─────────────────────┐
│   Sync Service      │
│                     │
│ 1. FFmpeg extracts  │
│    10min of audio   │
│                     │
│ 2. FFSubSync        │
│    analyzes speech  │
│    patterns         │
│                     │
│ 3. Returns synced   │
│    subtitle/offset  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Response:           │
│ - offset_ms: -1500  │
│ - synced_subtitle   │
│ - confidence        │
└─────────────────────┘
```

## 📡 API Endpoints

### `GET /` - Health check
```json
{
  "status": "healthy",
  "service": "Subtitle Sync Service",
  "version": "1.1.0"
}
```

### `GET /health` - Detailed health
```json
{
  "status": "healthy",
  "ffmpeg": "ok",
  "ffsubsync": "ok",
  "alass": "ok"
}
```

### `POST /sync` - Full synchronization
Synchronizes subtitle with video stream. Returns full synced subtitle.

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
  "confidence": 0.9,
  "message": "Synchronized successfully. Offset: -1500ms",
  "processing_time_ms": 45000
}
```

### `POST /offset` - Offset only (lightweight)
Same as `/sync` but returns only offset, not full subtitle. Better for mobile apps.

## 🚀 Deployment

### Deploy to Render.com (Free Tier)

1. **Fork this repository**

2. **Go to [render.com](https://render.com)** and sign up

3. **Create new Web Service:**
   - Connect your GitHub repository
   - Render will auto-detect `render.yaml`
   - Select **Free** plan
   - Click **Create Web Service**

4. **Wait for build** (~5 minutes)

5. **Use your service URL:**
   ```
   https://your-service-name.onrender.com
   ```

### Limitations (Free Tier)
- ⏰ Service sleeps after 15 min of inactivity
- 🐢 Cold start takes ~30-60 seconds
- 💾 512MB RAM limit
- 🕐 Sync takes 30-90 seconds per request

## 🛠️ Local Development

### With Docker
```bash
docker build -t subtitle-sync .
docker run -p 8000:8000 subtitle-sync
```

### With Python
```bash
# Install ffmpeg first
brew install ffmpeg  # macOS
apt install ffmpeg   # Ubuntu

# Install Python dependencies
pip install -r requirements.txt
pip install ffsubsync

# Run
python main.py
```

### Test the API
```bash
curl -X POST http://localhost:8000/offset \
  -H "Content-Type: application/json" \
  -d '{
    "stream_url": "https://example.com/video.mp4",
    "subtitle": "1\n00:00:01,000 --> 00:00:04,000\nTest subtitle\n\n",
    "language": "en"
  }'
```

## 📱 Integration Example (Android/Kotlin)

```kotlin
suspend fun syncSubtitle(streamUrl: String, subtitleContent: String): Int {
    val json = JSONObject().apply {
        put("stream_url", streamUrl)
        put("subtitle", subtitleContent)
        put("language", "en")
    }
    
    val request = Request.Builder()
        .url("https://your-service.onrender.com/offset")
        .post(json.toString().toRequestBody("application/json".toMediaType()))
        .build()
    
    val response = client.newCall(request).execute()
    val result = JSONObject(response.body?.string() ?: "{}")
    
    return if (result.optBoolean("success")) {
        result.optInt("offset_ms", 0)
    } else {
        0
    }
}
```

## 🔬 Technical Details

### FFSubSync
- Analyzes first 10 minutes of audio
- Detects speech patterns using WebRTC VAD
- Aligns subtitle timing with detected speech
- More accurate than simple offset detection

### alass (Fallback)
- Fast subtitle aligner written in Rust
- Used if FFSubSync fails
- Simpler algorithm but still effective

### Offset Calculation
- Compares first 5 subtitle timings
- Uses **median** offset (more robust than average)
- Handles variable-speed subtitles

## 📄 License

MIT License - feel free to use in your projects!

## 🙏 Acknowledgments

- [FFSubSync](https://github.com/smacke/ffsubsync) - The core synchronization engine
- [alass](https://github.com/kaegi/alass) - Fast subtitle aligner fallback
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
