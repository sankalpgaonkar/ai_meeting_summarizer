import threading
from typing import Optional, List, Union

import numpy as np
from faster_whisper import WhisperModel

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class TranscriptionService:
    _instance: Optional["TranscriptionService"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.model: Optional[WhisperModel] = None
        self._model_lock = threading.RLock()
        self._initialized = True

    def load_model(self) -> bool:
        with self._model_lock:
            if self.model is not None:
                return True
            try:
                logger.info(f"Loading Whisper model: {config.whisper.MODEL_SIZE} ({config.whisper.COMPUTE_TYPE})")
                # Optimize model loading - use smaller model for real-time
                model_size = config.whisper.MODEL_SIZE
                if model_size not in ("tiny", "base"):
                    logger.warning(f"Using larger model '{model_size}' - expect slower processing")
                self.model = WhisperModel(
                    config.whisper.MODEL_SIZE,
                    compute_type=config.whisper.COMPUTE_TYPE,
                    cpu_threads=config.whisper.CPU_THREADS,
                    num_workers=1,
                )
                logger.info("Whisper model loaded")
                return True
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                return False

    def is_ready(self) -> bool:
        return self.model is not None

    def transcribe(self, audio: Union[np.ndarray, str], language: Optional[str] = None) -> dict:
        # Quick early return if not ready
        if not self.is_ready():
            if not self.load_model():
                return {"text": "", "segments": [], "language": None, "error": "model_not_loaded"}

        # Optimize audio preprocessing
        try:
            # Check if conversion needed - faster path for float32
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            # Remove channels efficiently
            if audio.ndim > 1:
                audio = audio.mean(axis=1)

            with self._model_lock:
                segments_iter, info = self.model.transcribe(
                    audio,
                    beam_size=config.whisper.BEAM_SIZE,
                    language=language or config.whisper.LANGUAGE,
                    task="transcribe",
                    vad_filter=True,  # Voice activity detection - improves speed
                    vad_parameters={"min_silence_duration_ms": 500},
                )
                # Process segments more efficiently
                segments = []
                text_parts = []
                for seg in segments_iter:
                    text = seg.text.strip()
                    if text:  # Skip empty segments
                        segments.append({
                            "start": float(seg.start),
                            "end": float(seg.end),
                            "text": text,
                        })
                        text_parts.append(text)
                return {
                    "text": " ".join(text_parts).strip(),
                    "segments": segments,
                    "language": getattr(info, "language", None),
                }
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return {"text": "", "segments": [], "language": None, "error": str(e)}

    def transcribe_streaming(self, audio: np.ndarray, accumulated: str, language: Optional[str] = None) -> dict:
        result = self.transcribe(audio, language)
        if not result.get("text"):
            return {"partial": "", "full": accumulated, "segments": []}
        if accumulated:
            new_full = (accumulated.rstrip() + " " + result["text"]).strip()
        else:
            new_full = result["text"]
        return {
            "partial": result["text"],
            "full": new_full,
            "segments": result.get("segments", []),
            "language": result.get("language"),
        }


transcription_service = TranscriptionService()
