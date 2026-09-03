import os
import uuid
import re
from typing import Optional

from werkzeug.datastructures import FileStorage

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    pass


def validate_video_upload(file: FileStorage) -> None:
    """Optimized: use content_length from headers instead of seeking (much faster for large files)."""
    if not file or not file.filename:
        raise ValidationError("No file uploaded")

    filename = secure_filename(file.filename)

    if not allowed_video_extension(filename):
        raise ValidationError(
            f"File type not allowed. Allowed: {', '.join(config.storage.ALLOWED_VIDEO_TYPES)}"
        )

    # Accurately verify file size using seek/tell (instantaneous on file descriptor)
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)

    max_bytes = config.storage.MAX_VIDEO_SIZE_MB * 1024 * 1024
    if size > max_bytes:
        raise ValidationError(
            f"File too large: {size / 1024 / 1024:.1f}MB exceeds limit of {config.storage.MAX_VIDEO_SIZE_MB}MB"
        )
    if size == 0:
        raise ValidationError("Uploaded file is empty (0 bytes)")


def allowed_video_extension(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ["mp4", "webm", "mov", "avi", "mkv"]


def secure_filename(filename: str) -> str:
    filename = re.sub(r"[^\w\s.-]", "", filename).strip()
    filename = filename.replace("..", "")
    return filename[:200] or f"upload_{uuid.uuid4().hex[:8]}"


def generate_id() -> str:
    return uuid.uuid4().hex


def validate_title(title: Optional[str]) -> str:
    from datetime import datetime
    if not title:
        return f"Meeting {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    title = secure_filename(title)
    if not title:
        return f"Meeting {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    return title[:200]
