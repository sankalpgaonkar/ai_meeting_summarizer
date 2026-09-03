import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime


_LOGGERS = {}


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"app-{datetime.utcnow().strftime('%Y%m%d')}.log")

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers = [file_handler, stream_handler]

    for noisy in ["werkzeug", "urllib3", "google", "httpx", "ctranslate2", "faster_whisper"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root


def get_logger(name: str) -> logging.Logger:
    if name not in _LOGGERS:
        _LOGGERS[name] = logging.getLogger(name)
    return _LOGGERS[name]
