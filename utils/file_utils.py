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
    upload_base = ensure_dir(config.storage.UPLOAD_DIR)
    temp_dir = tempfile.mkdtemp(prefix="meeting_", dir=upload_base)
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
    upload_base = ensure_dir(config.storage.UPLOAD_DIR)
    temp_dir = tempfile.mkdtemp(prefix="meeting_", dir=upload_base)
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


def extract_audio_from_video(video_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """Extract compressed mono audio track from video file in milliseconds using ffmpeg."""
    import subprocess
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.warning(f"imageio_ffmpeg not available: {e}")
        ffmpeg_exe = "ffmpeg"

    if not output_path:
        base, _ = os.path.splitext(video_path)
        output_path = f"{base}_audio.mp3"

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "96k",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Extracted audio track to {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")
            return output_path
    except Exception as e:
        logger.error(f"Audio extraction error: {e}")

    return None
