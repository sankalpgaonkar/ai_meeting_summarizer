import time
import threading
import queue
from dataclasses import dataclass, field
from typing import List, Optional, Callable

import numpy as np
import sounddevice as sd

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AudioState:
    recording: bool = False
    paused: bool = False
    started_at: Optional[float] = None
    chunks: List[np.ndarray] = field(default_factory=list)
    partial_buffer: List[np.ndarray] = field(default_factory=list)
    partial_text: str = ""
    last_partial_emit: float = 0.0
    last_volume: float = 0.0
    volume_history: List[float] = field(default_factory=list)
    stream: Optional[sd.InputStream] = None
    subscribers: List[Callable[[str, dict], None]] = field(default_factory=list)
    final_text: str = ""
    error: Optional[str] = None

    def reset(self):
        self.recording = False
        self.paused = False
        self.started_at = None
        self.chunks = []
        self.partial_buffer = []
        self.partial_text = ""
        self.last_partial_emit = 0.0
        self.last_volume = 0.0
        self.volume_history = []
        self.stream = None
        self.subscribers = []
        self.final_text = ""
        self.error = None


class AudioService:
    def __init__(self):
        self.state = AudioState()
        self._lock = threading.RLock()
        self._partial_thread: Optional[threading.Thread] = None
        self._partial_stop = threading.Event()

    def list_devices(self) -> List[dict]:
        try:
            devices = sd.query_devices()
            input_devices = []
            for i, d in enumerate(devices):
                if d.get("max_input_channels", 0) > 0:
                    input_devices.append({
                        "id": i,
                        "name": d.get("name"),
                        "channels": d.get("max_input_channels"),
                        "hostapi": d.get("hostapi"),
                    })
            return input_devices
        except Exception as e:
            logger.error(f"Failed to list devices: {e}")
            return []

    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.debug(f"Audio status: {status}")
        with self._lock:
            if not self.state.recording or self.state.paused:
                return
            data = indata.copy()
            self.state.chunks.append(data)
            self.state.partial_buffer.append(data)
            volume = float(np.sqrt(np.mean(data ** 2)))
            self.state.last_volume = volume
            self.state.volume_history.append(volume)
            if len(self.state.volume_history) > 200:
                self.state.volume_history = self.state.volume_history[-200:]

    def start(self) -> dict:
        with self._lock:
            if self.state.recording:
                return {"status": "already_recording"}
            try:
                self.state.reset()
                self.state.stream = sd.InputStream(
                    samplerate=config.audio.SAMPLERATE,
                    channels=config.audio.CHANNELS,
                    dtype=config.audio.DTYPE,
                    blocksize=config.audio.BLOCKSIZE,
                    callback=self._callback,
                )
                self.state.stream.start()
                self.state.recording = True
                self.state.started_at = time.time()
                self._partial_stop.clear()
                self._partial_thread = threading.Thread(
                    target=self._partial_emit_loop, daemon=True, name="partial-emit"
                )
                self._partial_thread.start()
                logger.info("Audio capture started")
                return {
                    "status": "started",
                    "samplerate": config.audio.SAMPLERATE,
                    "channels": config.audio.CHANNELS,
                    "device": sd.query_devices(kind="input").get("name", "default"),
                    "started_at": self.state.started_at,
                }
            except Exception as e:
                logger.error(f"Failed to start audio: {e}")
                self.state.error = str(e)
                return {"status": "error", "error": str(e)}

    def pause(self) -> dict:
        with self._lock:
            if not self.state.recording:
                return {"status": "not_recording"}
            self.state.paused = True
            return {"status": "paused"}

    def resume(self) -> dict:
        with self._lock:
            if not self.state.recording:
                return {"status": "not_recording"}
            self.state.paused = False
            return {"status": "resumed"}

    def stop(self) -> dict:
        with self._lock:
            if not self.state.recording:
                return {"status": "not_recording"}
            self.state.recording = False
            self.state.paused = False
            self._partial_stop.set()
            if self.state.stream:
                try:
                    self.state.stream.stop()
                    self.state.stream.close()
                except Exception as e:
                    logger.warning(f"Error stopping stream: {e}")
                self.state.stream = None
            if self._partial_thread and self._partial_thread.is_alive():
                self._partial_thread.join(timeout=2.0)
            duration = (time.time() - self.state.started_at) if self.state.started_at else 0
            logger.info(f"Audio capture stopped. Duration: {duration:.1f}s, chunks: {len(self.state.chunks)}")
            return {
                "status": "stopped",
                "duration_seconds": duration,
                "chunk_count": len(self.state.chunks),
                "final_text": self.state.final_text,
            }

    def get_combined_audio(self) -> Optional[np.ndarray]:
        with self._lock:
            if not self.state.chunks:
                return None
            return np.concatenate(self.state.chunks, axis=0)

    def get_status(self) -> dict:
        with self._lock:
            duration = (time.time() - self.state.started_at) if self.state.started_at and self.state.recording else 0
            return {
                "recording": self.state.recording,
                "paused": self.state.paused,
                "duration_seconds": duration,
                "chunk_count": len(self.state.chunks),
                "last_volume": self.state.last_volume,
                "partial_text": self.state.partial_text,
                "error": self.state.error,
            }

    def subscribe(self, callback: Callable[[str, dict], None]) -> None:
        with self._lock:
            self.state.subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str, dict], None]) -> None:
        with self._lock:
            if callback in self.state.subscribers:
                self.state.subscribers.remove(callback)

    def _emit(self, event: str, data: dict) -> None:
        with self._lock:
            subs = list(self.state.subscribers)
        for sub in subs:
            try:
                sub(event, data)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    def _partial_emit_loop(self):
        interval = config.audio.PARTIAL_INTERVAL_SEC
        while not self._partial_stop.is_set():
            self._partial_stop.wait(interval)
            if self._partial_stop.is_set():
                break
            with self._lock:
                if not self.state.recording or not self.state.partial_buffer:
                    continue
                buffer_copy = list(self.state.partial_buffer)
                self.state.partial_buffer = []
            try:
                combined = np.concatenate(buffer_copy, axis=0)
                self._emit("audio_buffer", {"audio": combined})
            except Exception as e:
                logger.error(f"Partial emit error: {e}")

    def update_partial_text(self, text: str, full_text: str) -> None:
        with self._lock:
            self.state.partial_text = text
            self.state.final_text = full_text
        self._emit("transcript", {"partial": text, "full": full_text})


audio_service = AudioService()
