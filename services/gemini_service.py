import json
import time
import re
import threading
from typing import Optional

import google.generativeai as genai

from config import config
from utils.logger import get_logger
from utils.file_utils import safe_remove

logger = get_logger(__name__)

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

Rules:
- Incorporate both audio and any visible slides / screen-share / diagrams.
- Be specific. No filler. No preamble. No markdown fences.
"""


class GeminiService:
    def __init__(self):
        self._configured = False
        self._configure()

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
        if not self.is_ready():
            return {**MOM_SCHEMA, "error": "gemini_not_configured"}
        uploaded = None
        try:
            logger.info(f"Uploading video to Gemini: {video_path}")
            uploaded = genai.upload_file(path=video_path, mime_type=mime_type)
            logger.info(f"Uploaded as: {uploaded.name}, state: {getattr(uploaded, 'state', 'unknown')}")
            self._wait_for_file_active(uploaded.name)
            model = genai.GenerativeModel(config.gemini.MODEL)
            response = model.generate_content(
                [VIDEO_PROMPT, uploaded],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    top_p=0.9,
                    max_output_tokens=4096,
                ),
            )
            text = getattr(response, "text", "") or ""
            raw_json = self._extract_json(text)
            mom = self._normalize(raw_json)
            mom["raw_response"] = text
            return mom
        except Exception as e:
            logger.error(f"Video MOM failed: {e}")
            return {**MOM_SCHEMA, "error": str(e)}
        finally:
            if uploaded:
                try:
                    genai.delete_file(uploaded.name)
                    logger.debug(f"Deleted uploaded file: {uploaded.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete uploaded file: {e}")

    def _wait_for_file_active(self, file_name: str, max_wait: int = 120):
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
            time.sleep(2)
        logger.warning(f"File did not become ACTIVE within {max_wait}s, proceeding anyway")


gemini_service = GeminiService()
