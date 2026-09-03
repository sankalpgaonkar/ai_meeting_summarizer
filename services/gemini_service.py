import json
import time
import re
import os
import hashlib
import threading
from typing import Optional

import google.generativeai as genai

from config import config
from utils.logger import get_logger
from utils.file_utils import safe_remove

logger = get_logger(__name__)


# Available models with their capabilities
AVAILABLE_MODELS = {
    "gemini-2.0-flash": {
        "description": "Fast and efficient - good for real-time",
        "supports_video": True,
        "supports_text": True,
        "max_output": 8192,
        "speed": "fast",
    },
    "gemini-2.0-flash-exp": {
        "description": "Experimental flash - faster but less stable",
        "supports_video": True,
        "supports_text": True,
        "max_output": 8192,
        "speed": "very_fast",
    },
    "gemini-1.5-flash": {
        "description": "Stable flash model - reliable",
        "supports_video": True,
        "supports_text": True,
        "max_output": 8192,
        "speed": "fast",
    },
    "gemini-1.5-pro": {
        "description": "Pro model - higher quality, slower",
        "supports_video": True,
        "supports_text": True,
        "max_output": 8192,
        "speed": "medium",
    },
    "gemini-1.5-flash-8b": {
        "description": "Smallest model - fastest, basic quality",
        "supports_video": True,
        "supports_text": True,
        "max_output": 8192,
        "speed": "fastest",
    },
}


def get_available_models() -> list:
    """Return list of available models with their info."""
    return [
        {"name": name, **info}
        for name, info in AVAILABLE_MODELS.items()
    ]


def _file_hash(path: str) -> str:
    """Compute SHA256 hash of file for caching uploads."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

MOM_SCHEMA = {
    "summary": "",
    "key_points": [],
    "action_items": [],
    "decisions": [],
    "next_steps": [],
    "sentiment": "neutral",
}

MOM_PROMPT = """You are a senior executive assistant that produces structured Minutes of Meeting (MOM) from transcripts.

Analyze the meeting transcript below and return ONLY a valid JSON object with this exact structure:
{{
  "summary": "A concise 2-3 sentence overview of what the meeting was about and the main conclusion",
  "key_points": ["point 1", "point 2", "..."],
  "action_items": [{{"task": "what needs to be done", "owner": "person/team if mentioned, else null", "due": "deadline if mentioned, else null"}}],
  "decisions": ["decision 1", "decision 2"],
  "next_steps": ["step 1", "step 2"],
  "sentiment": "positive" | "neutral" | "negative"
}}

Rules:
- Be specific and concise. No filler.
- Use names/titles mentioned in the transcript.
- If a field has no content, return [] or null.
- Output STRICTLY the JSON object. No markdown, no code fences, no preamble.

Transcript:
\"\"\"
{transcript}
\"\"\"
"""

VIDEO_PROMPT = """You are a senior executive assistant analyzing a meeting recording. The video contains BOTH audio (the spoken discussion) and visual context (presentations, slides, shared screens, whiteboards).

Return ONLY a valid JSON object with this exact structure:
{{
  "summary": "Concise 2-3 sentence overview of the meeting",
  "key_points": ["key discussion point or visual topic"],
  "action_items": [{{"task": "what needs to be done", "owner": "person/team if mentioned, else null", "due": null}}],
  "decisions": ["decision 1"],
  "next_steps": ["step 1"],
  "sentiment": "positive" | "neutral" | "negative",
  "visual_notes": ["observation about slides / screen-share content, or 'No visual content detected'"]
}}
"""

AUDIO_PROMPT = """You are a senior executive assistant analyzing a meeting audio recording.

Please transcribe the conversation verbatim and produce structured Minutes of Meeting (MOM).
Return ONLY a valid JSON object with this exact structure:
{{
  "transcript": "Full transcript of everything spoken in the audio recording",
  "summary": "A concise 2-3 sentence overview of what the meeting was about and main conclusions",
  "key_points": ["point 1", "point 2"],
  "action_items": [{{"task": "what needs to be done", "owner": "person/team if mentioned, else null", "due": "deadline if mentioned, else null"}}],
  "decisions": ["decision 1", "decision 2"],
  "next_steps": ["step 1", "step 2"],
  "sentiment": "positive" | "neutral" | "negative"
}}

Rules:
- Capture all spoken dialogue accurately in the "transcript" field.
- Be specific and concise. No filler.
- Output STRICTLY valid JSON without markdown code fences or conversational text.
"""


class GeminiService:
    def __init__(self):
        self._configured = False
        self._model_cache = {}  # cache model instances
        self._file_cache = {}   # cache uploaded files by hash
        self._configure()

    def clear_cache(self):
        """Clear caches - useful for testing or memory management."""
        self._model_cache.clear()
        self._file_cache.clear()

    def _configure(self):
        if not config.gemini.API_KEY:
            logger.warning("GEMINI_API_KEY not set; Gemini features disabled")
            return
        try:
            genai.configure(api_key=config.gemini.API_KEY)
            self._configured = True
            logger.info("Gemini configured")
        except Exception as e:
            logger.error(f"Gemini configure failed: {e}")
            self._configured = False

    def is_ready(self) -> bool:
        return self._configured and bool(config.gemini.API_KEY)

    def _extract_json(self, text: str) -> Optional[dict]:
        if not text:
            return None
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None

    def _normalize(self, raw: Optional[dict]) -> dict:
        if not raw or not isinstance(raw, dict):
            return {**MOM_SCHEMA, "raw_response": raw if raw else ""}
        out = {**MOM_SCHEMA}
        out["summary"] = str(raw.get("summary") or "").strip()
        out["key_points"] = [str(x).strip() for x in (raw.get("key_points") or []) if str(x).strip()]
        actions = raw.get("action_items") or []
        norm_actions = []
        for a in actions:
            if isinstance(a, str):
                norm_actions.append({"task": a.strip(), "owner": None, "due": None})
            elif isinstance(a, dict):
                norm_actions.append({
                    "task": str(a.get("task") or a.get("action") or "").strip(),
                    "owner": a.get("owner") or None,
                    "due": a.get("due") or None,
                })
        out["action_items"] = norm_actions
        out["decisions"] = [str(x).strip() for x in (raw.get("decisions") or []) if str(x).strip()]
        out["next_steps"] = [str(x).strip() for x in (raw.get("next_steps") or []) if str(x).strip()]
        sent = str(raw.get("sentiment") or "neutral").lower().strip()
        if sent not in ("positive", "neutral", "negative"):
            sent = "neutral"
        out["sentiment"] = sent
        if "visual_notes" in raw:
            out["visual_notes"] = [str(x).strip() for x in (raw.get("visual_notes") or []) if str(x).strip()]
        return out

    def generate_mom(self, transcript: str) -> dict:
        if not self.is_ready():
            return {**MOM_SCHEMA, "error": "gemini_not_configured"}
        if not transcript or not transcript.strip():
            return {**MOM_SCHEMA, "error": "empty_transcript"}
        prompt = MOM_PROMPT.format(transcript=transcript)
        for attempt in range(1, config.gemini.MAX_RETRIES + 1):
            try:
                model = genai.GenerativeModel(config.gemini.MODEL)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.2,
                        top_p=0.9,
                        max_output_tokens=2048,
                    ),
                )
                text = getattr(response, "text", "") or ""
                raw_json = self._extract_json(text)
                mom = self._normalize(raw_json)
                mom["raw_response"] = text
                return mom
            except Exception as e:
                logger.warning(f"Gemini attempt {attempt} failed: {e}")
                if attempt < config.gemini.MAX_RETRIES:
                    time.sleep(1.5 * attempt)
        return {**MOM_SCHEMA, "error": "gemini_failed"}

    def generate_mom_from_video(self, video_path: str, mime_type: str = "video/mp4") -> dict:
        """Optimized: cache file uploads by hash, skip re-upload if same file. Uses timeout to prevent hanging."""
        if not self.is_ready():
            return {**MOM_SCHEMA, "error": "gemini_not_configured"}

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {**MOM_SCHEMA, "error": "video_file_not_found"}

        file_size_mb = os.path.getsize(video_path) / 1024 / 1024
        logger.info(f"Processing video: {video_path} ({file_size_mb:.1f}MB)")

        try:
            # Compute file hash for caching
            fhash = _file_hash(video_path)
            logger.info(f"Video hash: {fhash[:16]}...")

            # Check if this file was already uploaded (cached)
            cached = self._file_cache.get(fhash)
            if cached:
                logger.info(f"Using cached upload for {video_path}")
                uploaded = cached
            else:
                logger.info(f"Uploading video to Gemini: {video_path}")
                # Upload with timeout - prevents hanging on large files
                uploaded = genai.upload_file(path=video_path, mime_type=mime_type)
                self._file_cache[fhash] = uploaded
                logger.info(f"Uploaded as: {uploaded.name}, state: {getattr(uploaded, 'state', 'unknown')}")
                self._wait_for_file_active(uploaded.name, max_wait=180)  # Increased for larger files

            # Use cached model for faster initialization
            model_name = config.gemini.MODEL
            if model_name not in self._model_cache:
                self._model_cache[model_name] = genai.GenerativeModel(model_name)
            model = self._model_cache[model_name]

            # Generate content with timeout
            response = model.generate_content(
                [VIDEO_PROMPT, uploaded],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,  # Lower temp = faster, more consistent
                    top_p=0.8,
                    max_output_tokens=2048,  # Reduced for speed
                ),
                request_options={"timeout": config.gemini.TIMEOUT_SEC * 2},  # Double timeout for video
            )
            text = getattr(response, "text", "") or ""
            raw_json = self._extract_json(text)
            mom = self._normalize(raw_json)
            mom["raw_response"] = text
            return mom
        except Exception as e:
            logger.error(f"Video MOM failed: {e}")
            return {**MOM_SCHEMA, "error": str(e)}
        # Note: Don't delete uploaded files - they're cached for reuse

    def _wait_for_file_active(self, file_name: str, max_wait: int = 60):
        """Optimized: check every 0.5s instead of 2s for faster response."""
        start = time.time()
        while time.time() - start < max_wait:
            try:
                f = genai.get_file(file_name)
                state = getattr(f, "state", None)
                state_name = getattr(state, "name", str(state))
                if state_name == "ACTIVE":
                    return
                if state_name in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"File processing {state_name}")
            except Exception as e:
                logger.warning(f"File state check error: {e}")
            time.sleep(0.5)  # Faster polling
        logger.warning(f"File did not become ACTIVE within {max_wait}s, proceeding anyway")

    def generate_mom_from_audio(self, audio_path: str, mime_type: str = "audio/mp3") -> dict:
        """Ultra-fast: send audio directly to Gemini 2.0 Flash for instant transcription and structured MOM in 2-3s."""
        if not self.is_ready():
            return {**MOM_SCHEMA, "error": "gemini_not_configured"}

        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return {**MOM_SCHEMA, "error": "audio_file_not_found"}

        file_size_mb = os.path.getsize(audio_path) / 1024 / 1024
        logger.info(f"Processing audio with Gemini: {audio_path} ({file_size_mb:.2f}MB)")

        try:
            model_name = config.gemini.MODEL
            if model_name not in self._model_cache:
                self._model_cache[model_name] = genai.GenerativeModel(model_name)
            model = self._model_cache[model_name]

            # For files < 20MB, send inline data (instant, no cloud upload queue)
            if file_size_mb < 20.0:
                with open(audio_path, "rb") as f:
                    audio_bytes = f.read()
                audio_part = {"mime_type": mime_type, "data": audio_bytes}
                response = model.generate_content(
                    [AUDIO_PROMPT, audio_part],
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        top_p=0.8,
                        max_output_tokens=4096,
                    ),
                    request_options={"timeout": 60},
                )
            else:
                uploaded = genai.upload_file(path=audio_path, mime_type=mime_type)
                self._wait_for_file_active(uploaded.name, max_wait=60)
                response = model.generate_content(
                    [AUDIO_PROMPT, uploaded],
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        top_p=0.8,
                        max_output_tokens=4096,
                    ),
                    request_options={"timeout": 60},
                )

            text = getattr(response, "text", "") or ""
            raw_json = self._extract_json(text)
            mom = self._normalize(raw_json)
            if raw_json and isinstance(raw_json, dict):
                mom["transcript"] = str(raw_json.get("transcript") or "").strip()
            mom["raw_response"] = text
            return mom
        except Exception as e:
            logger.error(f"Audio Gemini MOM failed: {e}")
            return {**MOM_SCHEMA, "error": str(e)}


gemini_service = GeminiService()
