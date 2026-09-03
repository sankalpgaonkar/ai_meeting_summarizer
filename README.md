# AI Meeting Summarizer

A production-ready web application that captures live meeting audio for real-time transcription and accepts video uploads for multimodal analysis using Google's Gemini 2.0 Flash.

## Features

- **Live Audio Capture**: Background-thread recording with `sounddevice` + `numpy`
- **Local Transcription**: Low-latency speech-to-text with `faster-whisper`
- **Real-time SSE Updates**: Live transcript streaming via Server-Sent Events
- **Volume Meter**: Real-time audio level visualization
- **Mic Test**: 3-second test to verify microphone is working
- **Multimodal Video Analysis**: Upload pre-recorded videos for combined audio + visual analysis
- **Structured MOM**: Summary, key points, action items, decisions, next steps, sentiment
- **Meeting History**: SQLite-backed storage with paginated list view
- **Export**: Download meeting as Markdown file
- **Production Features**: Structured logging, graceful shutdown, CORS, rate limiting, health checks

## Project Structure

```
ai_meeting_summarizer/
├── app.py                    # Flask app factory
├── run.py                    # Entry point with CLI args
├── config.py                 # Configuration management
├── db.py                     # SQLite database layer
├── requirements.txt          # Python dependencies
├── Dockerfile                # Production container image
├── docker-compose.yml        # Docker Compose deployment
├── .env.example              # Environment variable template
├── services/
│   ├── audio_service.py      # Sounddevice capture management
│   ├── transcription_service.py  # Whisper model wrapper
│   └── gemini_service.py     # Gemini API client
├── routes/
│   └── api.py                # Flask API blueprint
├── utils/
│   ├── logger.py             # Structured logging
│   ├── validators.py         # Input validation
│   └── file_utils.py         # File handling utilities
├── templates/
│   └── index.html            # Web UI
├── tests/
│   └── test_app.py           # Unit tests
├── data/                     # SQLite database
├── logs/                     # Application logs
└── uploads_tmp/              # Temporary video uploads
```

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy environment template and set your API key
cp .env.example .env
# Edit .env and add: GEMINI_API_KEY=your_actual_key

# Run the application
python run.py
```

The application will be available at `http://localhost:5001`.

### Docker Deployment

```bash
# Build and run
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Health check with component status |
| `GET` | `/api/meetings` | List meetings (paginated) |
| `GET` | `/api/meetings/<id>` | Get meeting details |
| `DELETE` | `/api/meetings/<id>` | Delete meeting |
| `GET` | `/api/export/<id>` | Export meeting as Markdown |
| `GET` | `/api/devices` | List audio input devices |
| `POST` | `/api/mic-test` | Test microphone (3-second sample) |
| `POST` | `/api/start` | Start live audio capture |
| `POST` | `/api/stop` | Stop capture, trigger analysis |
| `GET` | `/api/stream` | Server-Sent Events stream |
| `GET` | `/api/status` | Current recording status |
| `POST` | `/api/upload_video` | Upload video for multimodal analysis |

## Server-Sent Events

The `/api/stream` endpoint emits real-time events for the UI:

- `recording_started` - Capture has begun
- `partial_transcript` - Live partial transcript updates
- `processing_started` - Analysis pipeline initiated
- `transcription_started` / `transcription_complete` - Whisper status
- `analysis_started` - Gemini processing
- `processing_complete` - Analysis finished
- `processing_error` - Error occurred

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (required) | Google Gemini API key |
| `WHISPER_MODEL` | `base` | Whisper model size: tiny, base, small, medium, large-v3 |
| `WHISPER_COMPUTE` | `int8` | Compute type: int8, float16, float32 |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `MAX_VIDEO_SIZE_MB` | `100` | Max upload size in MB |
| `PORT` | `5001` | Server port |
| `FLASK_DEBUG` | `false` | Enable debug mode |
| `SECRET_KEY` | (random) | Flask secret for sessions |

## Whisper Model Sizes

| Model | Size | RAM | Speed | Accuracy |
|-------|------|-----|-------|----------|
| tiny | 39M | ~1GB | Fastest | Lowest |
| base | 74M | ~1GB | Fast | Good |
| small | 244M | ~2GB | Medium | Better |
| medium | 769M | ~5GB | Slow | High |
| large-v3 | 1550M | ~10GB | Slowest | Best |

For real-time transcription, use `tiny` or `base`. For higher accuracy, use `small` or `medium`.

## Requirements

- Python 3.9+
- PortAudio (`brew install portaudio` on macOS, `apt install portaudio19-dev` on Linux)
- Microphone access
- ~2GB disk for Whisper model
- ~500MB RAM minimum

## License

MIT