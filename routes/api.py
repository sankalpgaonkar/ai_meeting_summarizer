import time
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify, Response, stream_with_context

from config import config
from db import db, Meeting
from services.audio_service import audio_service
from services.transcription_service import transcription_service
from services.gemini_service import gemini_service
from utils.validators import validate_video_upload, secure_filename, generate_id
from utils.file_utils import save_upload_to_temp, safe_remove
from utils.logger import get_logger

logger = get_logger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

_current_sse_subscribers = []
_sse_lock = threading.RLock()


def sse_add(subscriber):
    with _sse_lock:
        if subscriber not in _current_sse_subscribers:
            _current_sse_subscribers.append(subscriber)


def sse_remove(subscriber):
    with _sse_lock:
        if subscriber in _current_sse_subscribers:
            _current_sse_subscribers.remove(subscriber)


def emit_sse(event: str, data: dict):
    payload = f"event: {event}\ndata: {data}\n\n"
    dead = []
    with _sse_lock:
        for sub in _current_sse_subscribers:
            try:
                sub(payload.encode("utf-8"))
            except Exception:
                dead.append(sub)
        for d in dead:
            _current_sse_subscribers.remove(d)


@api.route("/health", methods=["GET"])
def health():
    components = {
        "api": "ok",
        "whisper": "ok" if transcription_service.is_ready() else "loading",
        "gemini": "ok" if gemini_service.is_ready() else "not_configured",
        "audio": "ok",
    }
    return jsonify({"status": "ok", "components": components})


@api.route("/meetings", methods=["GET"])
def list_meetings():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(per_page, 100)
    meetings, total = db.get_meetings(page=page, per_page=per_page)
    return jsonify({
        "meetings": [m.to_dict() for m in meetings],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    })


@api.route("/meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id):
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    return jsonify(meeting.to_dict())


@api.route("/meetings/<meeting_id>", methods=["DELETE"])
def delete_meeting(meeting_id):
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if meeting.video_filename:
        safe_remove(meeting.video_filename)
    db.delete_meeting(meeting_id)
    return jsonify({"status": "deleted", "id": meeting_id})


@api.route("/export/<meeting_id>", methods=["GET"])
def export_meeting(meeting_id):
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    lines = [
        f"# {meeting.title}",
        f"**Date:** {meeting.created_at}",
        f"**Duration:** {meeting.duration_seconds}s",
        f"**Source:** {meeting.source}",
        "",
        "## Transcript",
        meeting.transcript or "_No transcript captured_",
        "",
        "## Summary",
        meeting.summary or "_No summary available_",
        "",
    ]
    if meeting.key_points:
        lines.append("## Key Points")
        for point in meeting.key_points:
            lines.append(f"- {point}")
        lines.append("")
    if meeting.action_items:
        lines.append("## Action Items")
        for item in meeting.action_items:
            owner = f" (**Owner:** {item['owner']})" if item.get("owner") else ""
            due = f" (**Due:** {item['due']})" if item.get("due") else ""
            lines.append(f"- [ ] {item['task']}{owner}{due}")
        lines.append("")
    if meeting.decisions:
        lines.append("## Decisions")
        for d in meeting.decisions:
            lines.append(f"- {d}")
        lines.append("")
    if meeting.next_steps:
        lines.append("## Next Steps")
        for s in meeting.next_steps:
            lines.append(f"- {s}")
        lines.append("")
    if meeting.sentiment:
        lines.append(f"**Sentiment:** {meeting.sentiment.title()}")
    content = "\n".join(lines)
    safe_filename = secure_filename(meeting.title).replace(" ", "_")
    filename = f"{safe_filename}_{meeting_id[:8]}.md"
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@api.route("/devices", methods=["GET"])
def list_devices():
    devices = audio_service.list_devices()
    return jsonify({"devices": devices})


@api.route("/mic-test", methods=["POST"])
def mic_test():
    result = audio_service.start()
    if result.get("status") != "started":
        return jsonify({"error": "Failed to start mic", "details": result}), 500
    time.sleep(3)
    stop_result = audio_service.stop()
    status = audio_service.get_status()
    volume = status.get("last_volume", 0)
    if volume < config.audio.MIN_VOLUME_THRESHOLD:
        quality = "silent"
        message = "Mic detected but only silence/noise. Check if your mic is working and try speaking."
    elif volume < 0.05:
        quality = "low"
        message = "Mic level is low. Try moving closer or increasing system mic volume."
    elif volume > 0.8:
        quality = "high"
        message = "Mic level is good but quite loud. You may want to reduce input volume."
    else:
        quality = "good"
        message = "Mic level is optimal."
    return jsonify({
        "volume": round(volume, 4),
        "quality": quality,
        "message": message,
        "duration_seconds": stop_result.get("duration_seconds", 3),
        "chunks": stop_result.get("chunk_count", 0),
    })


@api.route("/start", methods=["POST"])
def start_capture():
    data = request.get_json(silent=True) or {}
    title = data.get("title") or f"Meeting {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    meeting_id = generate_id()
    meeting = Meeting(
        id=meeting_id,
        title=title,
        transcript="",
        summary=None,
        status="recording",
        source="live",
    )
    db.create_meeting(meeting)
    result = audio_service.start()
    emit_sse("recording_started", {"meeting_id": meeting_id, "title": title, **result})
    return jsonify({"status": "started", "meeting_id": meeting_id, **result})


@api.route("/stop", methods=["POST"])
def stop_capture():
    data = request.get_json(silent=True) or {}
    meeting_id = data.get("meeting_id")
    stop_result = audio_service.stop()
    if stop_result.get("status") == "not_recording":
        return jsonify({"status": "not_recording"}), 400
    if not meeting_id:
        return jsonify({"error": "meeting_id required"}), 400
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    meeting.status = "processing"
    db.update_meeting(meeting)
    emit_sse("processing_started", {"meeting_id": meeting_id})
    audio_data = audio_service.get_combined_audio()
    if audio_data is None or len(audio_data) == 0:
        meeting.status = "empty"
        meeting.summary = "No audio was captured during this session. Please check your microphone permissions and try again."
        db.update_meeting(meeting)
        emit_sse("processing_complete", {"meeting_id": meeting_id, "status": "empty"})
        return jsonify({"status": "stopped", "meeting_id": meeting_id, "empty": True})
    thread = threading.Thread(
        target=_process_meeting_thread,
        args=(meeting_id, audio_data),
        daemon=True,
        name=f"process-meeting-{meeting_id[:8]}",
    )
    thread.start()
    return jsonify({
        "status": "stopped",
        "meeting_id": meeting_id,
        "duration_seconds": stop_result.get("duration_seconds", 0),
    })


def _process_meeting_thread(meeting_id, audio_data):
    try:
        emit_sse("transcription_started", {"meeting_id": meeting_id})
        transcript_result = transcription_service.transcribe(audio_data)
        transcript_text = transcript_result.get("text", "")
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            return
        meeting.transcript = transcript_text
        meeting.duration_seconds = int(audio_data.shape[0] / config.audio.SAMPLERATE)
        meeting.status = "transcribed"
        db.update_meeting(meeting)
        emit_sse("transcription_complete", {
            "meeting_id": meeting_id,
            "transcript": transcript_text,
        })
        if not transcript_text.strip():
            meeting.summary = "No speech was detected in the recording. Please ensure the microphone was active and participants were speaking."
            meeting.status = "no_speech"
            db.update_meeting(meeting)
            emit_sse("processing_complete", {"meeting_id": meeting_id, "status": "no_speech"})
            return
        emit_sse("analysis_started", {"meeting_id": meeting_id})
        mom = gemini_service.generate_mom(transcript_text)
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            return
        if mom.get("error"):
            meeting.summary = f"Analysis error: {mom.get('error')}"
            meeting.status = "error"
        else:
            meeting.summary = mom.get("summary")
            meeting.key_points = mom.get("key_points", [])
            meeting.action_items = mom.get("action_items", [])
            meeting.decisions = mom.get("decisions", [])
            meeting.next_steps = mom.get("next_steps", [])
            meeting.sentiment = mom.get("sentiment")
            meeting.raw_mom = mom.get("raw_response")
            meeting.status = "complete"
        db.update_meeting(meeting)
        emit_sse("processing_complete", {
            "meeting_id": meeting_id,
            "status": meeting.status,
            "summary": meeting.summary,
        })
        logger.info(f"Meeting {meeting_id} processing complete: {meeting.status}")
    except Exception as e:
        logger.error(f"Processing thread error for {meeting_id}: {e}")
        try:
            meeting = db.get_meeting(meeting_id)
            if meeting:
                meeting.status = "error"
                meeting.summary = f"Processing failed: {str(e)}"
                db.update_meeting(meeting)
        except Exception:
            pass
        emit_sse("processing_error", {"meeting_id": meeting_id, "error": str(e)})


@api.route("/stream")
def sse_stream():
    import queue

    def generator():
        q = queue.Queue()
        done = threading.Event()

        def callback(data):
            try:
                q.put(data)
            except Exception:
                pass

        sse_add(callback)
        try:
            yield b": connected\n\n"
            while not done.is_set():
                try:
                    data = q.get(timeout=20)
                    if data is None:
                        break
                    yield data
                except queue.Empty:
                    yield b": keepalive\n\n"
        finally:
            sse_remove(callback)

    response = Response(
        stream_with_context(generator()),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@api.route("/status", methods=["GET"])
def get_status():
    audio_status = audio_service.get_status()
    return jsonify({
        "audio": audio_status,
        "whisper_ready": transcription_service.is_ready(),
        "gemini_ready": gemini_service.is_ready(),
    })


@api.route("/upload_video", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file uploaded"}), 400
    video_file = request.files["video"]
    try:
        validate_video_upload(video_file)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    meeting_id = generate_id()
    title = request.form.get("title") or f"Video Meeting {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    video_path = None
    temp_dir = None
    meeting = Meeting(
        id=meeting_id,
        title=title,
        transcript="",
        summary=None,
        status="uploading",
        source="video",
    )
    db.create_meeting(meeting)
    emit_sse("video_upload_started", {"meeting_id": meeting_id})
    try:
        video_path, temp_dir = save_upload_to_temp(video_file)
        meeting.video_filename = video_path
        meeting.status = "processing_video"
        db.update_meeting(meeting)
        emit_sse("video_upload_complete", {"meeting_id": meeting_id})
        emit_sse("processing_started", {"meeting_id": meeting_id})
        mime_type = video_file.content_type or "video/mp4"
        mom = gemini_service.generate_mom_from_video(video_path, mime_type)
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404
        if mom.get("error"):
            meeting.summary = f"Analysis error: {mom.get('error')}"
            meeting.status = "error"
        else:
            meeting.summary = mom.get("summary")
            meeting.key_points = mom.get("key_points", [])
            meeting.action_items = mom.get("action_items", [])
            meeting.decisions = mom.get("decisions", [])
            meeting.next_steps = mom.get("next_steps", [])
            meeting.sentiment = mom.get("sentiment")
            meeting.raw_mom = mom.get("raw_response")
            meeting.status = "complete"
        db.update_meeting(meeting)
        emit_sse("processing_complete", {
            "meeting_id": meeting_id,
            "status": meeting.status,
            "summary": meeting.summary,
        })
        return jsonify({
            "status": "success",
            "meeting_id": meeting_id,
            "result": meeting.to_dict(),
        })
    except Exception as e:
        logger.error(f"Video upload error: {e}")
        try:
            meeting = db.get_meeting(meeting_id)
            if meeting:
                meeting.status = "error"
                meeting.summary = f"Upload failed: {str(e)}"
                db.update_meeting(meeting)
        except Exception:
            pass
        emit_sse("processing_error", {"meeting_id": meeting_id, "error": str(e)})
        return jsonify({"error": str(e)}), 500
    finally:
        if temp_dir:
            safe_remove(temp_dir)
