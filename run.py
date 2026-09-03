import os
import sys
import argparse

from app import app
from config import config
from utils.logger import setup_logging, get_logger


def main():
    setup_logging()
    logger = get_logger("run")

    parser = argparse.ArgumentParser(description="AI Meeting Summarizer")
    parser.add_argument("--host", default=config.app.HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=config.app.PORT, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", default=config.app.DEBUG, help="Enable debug mode")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers (use 1 for audio capture)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("AI Meeting Summarizer")
    logger.info("=" * 60)
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Debug: {args.debug}")
    logger.info(f"Whisper: {config.whisper.MODEL_SIZE} ({config.whisper.COMPUTE_TYPE})")
    logger.info(f"Gemini: {config.gemini.MODEL} (configured: {bool(config.gemini.API_KEY)})")
    logger.info(f"Database: {config.storage.DB_PATH}")
    logger.info("=" * 60)

    if not config.gemini.API_KEY:
        logger.warning("GEMINI_API_KEY not set - Gemini features will be unavailable")

    try:
        from services.transcription_service import transcription_service
        logger.info("Pre-loading Whisper model...")
        transcription_service.load_model()
        logger.info("Whisper model ready")
    except Exception as e:
        logger.error(f"Failed to pre-load Whisper model: {e}")
        logger.info("Model will be loaded on first use")

    try:
        app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            threaded=True,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
