import os
import tempfile
import shutil
from typing import Optional

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.remove(path)
            logger.debug(f"Removed file: {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.debug(f"Removed directory: {path}")
    except OSError as e:
        logger.warning(f"Failed to remove {path}: {e}")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def save_upload_to_temp(file_storage, suffix: Optional[str] = None) -> tuple[str, str]:
    temp_dir = ensure_dir(tempfile.mkdtemp(prefix="meeting_", dir=config.storage.UPLOAD_DIR))
    filename = file_storage.filename or "upload"
    if suffix:
        base, ext = os.path.splitext(filename)
        filename = f"{base}{suffix}{ext}"
    safe_path = os.path.join(temp_dir, filename)
    file_storage.save(safe_path)
    logger.info(f"Saved upload to {safe_path}")
    return safe_path, temp_dir
