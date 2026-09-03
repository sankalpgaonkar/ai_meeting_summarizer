import atexit
import signal
import sys
import os

from flask import Flask, render_template, jsonify

from config import config
from routes.api import api as api_blueprint
from utils.logger import setup_logging, get_logger


def create_app() -> Flask:
    setup_logging()
    logger = get_logger("app")
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = config.app.SECRET_KEY
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = config.storage.MAX_VIDEO_SIZE_MB * 1024 * 1024

    app.register_blueprint(api_blueprint)

    @app.route("/")
    def index():
        return render_template("index.html", config={"max_video_mb": config.storage.MAX_VIDEO_SIZE_MB})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": f"File too large. Max size: {config.storage.MAX_VIDEO_SIZE_MB}MB"}), 413

    @app.errorhandler(500)
    def server_error(e):
        logger.error(f"Server error: {e}")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

    def shutdown_handler(*args):
        logger.info("Shutdown signal received, cleaning up...")
        try:
            from services.audio_service import audio_service
            if audio_service.state.recording:
                audio_service.stop()
        except Exception as e:
            logger.error(f"Shutdown cleanup error: {e}")
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)
    atexit.register(shutdown_handler)

    logger.info(f"App created. Debug={config.app.DEBUG}, Port={config.app.PORT}")
    return app


app = create_app()
