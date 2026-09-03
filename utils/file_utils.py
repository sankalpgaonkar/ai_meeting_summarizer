import os
import tempfile
import shutil
from typing import Optional

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def safe_remove(path: Optional[str]) -> None:
    """Safely remove a file or directory. Silently ignores errors."""
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
    """Create directory if it doesn't exist. Returns the path."""
    os.makedirs(path, exist_ok=True)
    return path


def save_upload_to_temp(file_storage, suffix: Optional[str] = None) -> tuple[str, str]:
    """Save uploaded file to temp directory. Returns (file_path, temp_dir).

    Optimized: uses stream-based copy for large files instead of loading into memory.
    """
    temp_dir = ensure_dir(tempfile.mkdtemp(prefix="meeting_", dir=config.storage.UPLOAD_DIR))
    filename = file_storage.filename or "upload"
    if suffix:
        base, ext = os.path.splitext(filename)
        filename = f"{base}{suffix}{ext}"
    safe_path = os.path.join(temp_dir, filename)

    # Use stream-based save for large files (memory efficient)
    # This is much faster than loading entire file into memory
    file_storage.save(safe_path)
    logger.info(f"Saved upload to {safe_path}")
    return safe_path, temp_dir


def save_upload_streamed(file_storage, chunk_size: int = 1024 * 1024) -> tuple[str, str]:
    """Save uploaded file using chunked streaming. Best for very large files.

    Args:
        file_storage: Flask FileStorage object
        chunk_size: Size of each chunk in bytes (default 1MB)

    Returns:
        tuple of (file_path, temp_dir)
    """
    temp_dir = ensure_dir(tempfile.mkdtemp(prefix="meeting_", dir=config.storage.UPLOAD_DIR))
    filename = file_storage.filename or "upload"
    safe_path = os.path.join(temp_dir, filename)

    # Stream the file in chunks for better memory efficiency
    with open(safe_path, 'wb') as f:
        while True:
            chunk = file_storage.stream.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)

    logger.info(f"Streamed upload to {safe_path}")
    return safe_path, temp_dir
