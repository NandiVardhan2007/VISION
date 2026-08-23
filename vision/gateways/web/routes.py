"""
FastAPI REST routes for VISION web dashboard and API access.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import json
import time
import os
import psutil
from datetime import datetime
from pathlib import Path

from vision.core.engine import vision_engine
from vision.perception.stt import smart_stt
from vision.perception.vision.screen import screen_capture
from vision.tools.registry import tool_registry
from vision.config import config
from vision.cognitive.load_balancer import load_balancer
from vision.memory.mag_engine import mag_engine
from vision.memory.cag_engine import cag_engine
from vision.memory.working_memory import working_memory
from vision.core.session import session_manager
from vision.logger import logger

router = APIRouter()
stt = smart_stt

START_TIME = time.time()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "web_session"
    synthesize_voice: Optional[bool] = True


class ToolExecRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = {}


class RememberRequest(BaseModel):
    content: str
    category: Optional[str] = "user_preference"
    tags: Optional[str] = ""


class ForgetRequest(BaseModel):
    query: str


class SynthesizeRequest(BaseModel):
    text: str


class SaveSessionRequest(BaseModel):
    session_id: str
    transcripts: List[Dict[str, Any]]
    total_messages: Optional[int] = 0
    exported_at: Optional[str] = None


@router.get("/health")
async def health():
    return {
        "status": "online",
        "load_balancer_endpoints": len(load_balancer.providers),
        "tools_registered": len(tool_registry.get_all_schemas()),
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "model": config.VISION_LLM_MODEL,
        "mode": "autonomous_os"
    }


@router.get("/system/stats")
async def get_system_stats():
    """Retrieve real-time hardware telemetry and load balancer status."""
    try:
        # CPU
        cpu_overall = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
        cpu_freq = psutil.cpu_freq()
        
        # RAM
        vmem = psutil.virtual_memory()
        
        # Battery
        battery = psutil.sensors_battery()
        battery_data = None
        if battery:
            battery_data = {
                "percent": battery.percent,
                "power_plugged": battery.power_plugged,
                "secs_left": battery.secsleft if battery.secsleft > 0 else None
            }
            
        # Storage
        disks = []
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disks.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": usage.percent
                })
            except Exception:
                pass

        # Top processes
        top_processes = []
        try:
            for p in sorted(
                psutil.process_iter(['name', 'cpu_percent', 'memory_info']),
                key=lambda x: x.info.get('memory_info').rss if x.info.get('memory_info') else 0,
                reverse=True
            )[:5]:
                try:
                    top_processes.append({
                        "name": p.info['name'],
                        "cpu": p.info.get('cpu_percent', 0.0),
                        "mem_mb": round(p.info['memory_info'].rss / (1024 * 1024), 1) if p.info.get('memory_info') else 0
                    })
                except Exception:
                    pass
        except Exception:
            pass

        # Net I/O
        net = psutil.net_io_counters()

        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_seconds": round(time.time() - START_TIME),
            "cpu": {
                "percent": cpu_overall,
                "cores": cpu_cores,
                "core_count": psutil.cpu_count(logical=True),
                "frequency_ghz": round(cpu_freq.current / 1000, 2) if cpu_freq else 0
            },
            "ram": {
                "percent": vmem.percent,
                "total_gb": round(vmem.total / (1024**3), 1),
                "used_gb": round(vmem.used / (1024**3), 1),
                "free_gb": round(vmem.available / (1024**3), 1)
            },
            "battery": battery_data,
            "storage": disks,
            "network": {
                "bytes_sent_mb": round(net.bytes_sent / (1024 * 1024), 1),
                "bytes_recv_mb": round(net.bytes_recv / (1024 * 1024), 1)
            },
            "top_processes": top_processes,
            "load_balancer": {
                "strategy": config.VISION_LOAD_BALANCER_STRATEGY,
                "primary_model": config.VISION_LLM_MODEL,
                "nim_model": config.VISION_NIM_LLM_MODEL,
                "provider_count": len(load_balancer.providers)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to gather system stats: {e}")


@router.get("/memory/stats")
async def get_memory_stats():
    """Retrieve full MAG and CAG memory telemetry and records."""
    try:
        memories = mag_engine.list_all(limit=50)
        events = mag_engine.get_recent_events(limit=20)
        cag_stats = cag_engine.get_stats()
        working_stats = {
            "recent_files_count": len(working_memory.recent_files),
            "indexed_files_count": len(working_memory.file_index),
            "last_directory": working_memory.last_directory,
            "last_opened_app": working_memory.last_opened_app
        }
        return {
            "semantic_memories": memories,
            "episodic_events": events,
            "cag_cache": cag_stats,
            "working_memory": working_stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load memory telemetry: {e}")



@router.post("/memory/remember")
async def remember_memory(req: RememberRequest):
    mem_id = mag_engine.remember(req.content, category=req.category, tags=req.tags)
    return {"status": "success", "id": mem_id, "content": req.content}


@router.post("/memory/forget")
async def forget_memory(req: ForgetRequest):
    deleted = mag_engine.forget(req.query)
    return {"status": "success", "deleted_count": deleted}


@router.post("/chat")
async def chat(req: ChatRequest):
    try:
        result = await vision_engine.process_user_input(
            user_text=req.message,
            session_id=req.session_id or "web_session",
            synthesize_voice=req.synthesize_voice or False
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    Server-Sent Events (SSE) streaming endpoint for real-time word-by-word transcription.
    Streams tokens in real-time as they are generated and spoken by VISION.
    """
    async def event_generator():
        token_queue: asyncio.Queue = asyncio.Queue()
        session_id = req.session_id or "web_stream_session"

        async def _token_cb(token: str):
            await token_queue.put({"type": "token", "token": token})

        async def _run_engine():
            try:
                res = await vision_engine.process_user_input(
                    user_text=req.message,
                    session_id=session_id,
                    channel="web_stream",
                    synthesize_voice=req.synthesize_voice if req.synthesize_voice is not None else True,
                    token_callback=_token_cb
                )
                await token_queue.put({
                    "type": "done",
                    "response": res.get("response", ""),
                    "provider": res.get("provider", ""),
                    "latency_ms": res.get("latency_ms", 0)
                })
            except Exception as ex:
                await token_queue.put({"type": "error", "detail": str(ex)})
            finally:
                await token_queue.put(None)

        engine_task = asyncio.create_task(_run_engine())

        yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

        try:
            while True:
                item = await token_queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
                if item.get("type") in ("done", "error"):
                    break
        finally:
            if not engine_task.done():
                await engine_task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/tools")
async def list_tools():
    return {"tools": tool_registry.get_all_schemas()}


@router.post("/tools/execute")
async def execute_tool(req: ToolExecRequest):
    result = await tool_registry.execute(req.tool_name, req.arguments)
    return {"tool": req.tool_name, "result": result}


@router.post("/speech/synthesize")
async def synthesize_speech(req: SynthesizeRequest):
    if not vision_engine.tts:
        raise HTTPException(status_code=400, detail="Cartesia TTS engine not configured (API key missing).")
    try:
        audio_bytes = await vision_engine.tts.synthesize(req.text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Speech synthesis error: {e}")


@router.post("/audio/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        if not contents or len(contents) < 400:
            return {"text": ""}
        text = await stt.transcribe(contents, filename=file.filename)
        return {"text": text or ""}
    except Exception as e:
        logger.warning(f"[STT] Transcribe endpoint warning: {e}")
        return {"text": ""}


@router.post("/audio/stop")
async def stop_audio_playback():
    """Immediately stop TTS speech playback on server (Barge-In)."""
    try:
        from vision.synthesis.player import audio_player
        from vision.core.engine import vision_engine
        audio_player.stop()
        if hasattr(vision_engine, "stop_speech"):
            await vision_engine.stop_speech()
        return {"status": "stopped"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/vision/screenshot")
async def get_screenshot():
    jpeg_bytes = screen_capture.capture_screen()
    if not jpeg_bytes:
        raise HTTPException(status_code=500, detail="Failed to capture screen.")
    return Response(content=jpeg_bytes, media_type="image/jpeg")


# ── Task Tracker Endpoints ──
class TaskCreateRequest(BaseModel):
    title: str
    day: Optional[int] = None
    month: Optional[str] = None
    year: Optional[int] = None
    category: Optional[str] = "General"
    priority: Optional[str] = "Medium"


class TaskToggleRequest(BaseModel):
    completed: Optional[bool] = None


@router.get("/tasks/dashboard")
async def get_tasks_dashboard(day: Optional[int] = None, month: Optional[str] = None, year: Optional[int] = None):
    try:
        from vision.memory.task_tracker_db import task_db
        summary = task_db.get_dashboard_summary(day=day, month=month, year=year)
        return summary
    except Exception as e:
        logger.error(f"[API] Tasks dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def list_tasks(day: Optional[int] = None, month: Optional[str] = None, year: Optional[int] = None):
    try:
        from vision.memory.task_tracker_db import task_db
        if day:
            tasks = task_db.get_tasks_for_day(day=day, month=month, year=year)
        elif month:
            tasks = task_db.get_tasks_for_month(month=month, year=year)
        else:
            tasks = task_db.get_all_tasks(year=year)
        return {"tasks": tasks}
    except Exception as e:
        logger.error(f"[API] List tasks error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks")
async def create_task(req: TaskCreateRequest):
    try:
        from vision.memory.task_tracker_db import task_db
        from vision.tools.excel_tracker_engine import excel_tracker
        task = task_db.add_task(
            title=req.title,
            day=req.day,
            month=req.month,
            year=req.year,
            category=req.category or "General",
            priority=req.priority or "Medium"
        )
        try:
            excel_tracker.generate_workbook(year=task["year"])
        except Exception as ex:
            logger.warning(f"[API] Excel sync warning: {ex}")
        return {"status": "success", "task": task}
    except Exception as e:
        logger.error(f"[API] Create task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/tasks/{task_id}/toggle")
async def toggle_task(task_id: int, req: Optional[TaskToggleRequest] = None):
    try:
        from vision.memory.task_tracker_db import task_db
        from vision.tools.excel_tracker_engine import excel_tracker
        completed = req.completed if req else None
        task = task_db.toggle_task(task_id, completed=completed)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task #{task_id} not found.")
        try:
            excel_tracker.generate_workbook(year=task["year"])
        except Exception as ex:
            logger.warning(f"[API] Excel sync warning: {ex}")
        return {"status": "success", "task": task}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Toggle task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    try:
        from vision.memory.task_tracker_db import task_db
        from vision.tools.excel_tracker_engine import excel_tracker
        success = task_db.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Task #{task_id} not found.")
        try:
            excel_tracker.generate_workbook()
        except Exception as ex:
            logger.warning(f"[API] Excel sync warning: {ex}")
        return {"status": "deleted", "task_id": task_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Delete task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/excel/sync")
async def sync_excel_tracker():
    try:
        from vision.tools.excel_tracker_engine import excel_tracker
        path = excel_tracker.generate_workbook()
        return {"status": "success", "path": path}
    except Exception as e:
        logger.error(f"[API] Excel sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/excel/open")
async def open_excel_tracker():
    try:
        from vision.tools.task_tracker_tools import open_excel_tracker
        result = open_excel_tracker()
        return {"status": "success", "message": result}
    except Exception as e:
        logger.error(f"[API] Excel open error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Session Chat History & JSON Storage Endpoints ──
SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/sessions/save")
async def save_session_transcript(req: SaveSessionRequest):
    """Save/archive a session chat transcript as a JSON file."""
    try:
        # Sanitize session_id for filename
        clean_id = "".join(c for c in req.session_id if c.isalnum() or c in ("-", "_")).strip() or "session_unnamed"
        filename = f"{clean_id}.json"
        filepath = SESSIONS_DIR / filename
        data = {
            "session_id": req.session_id,
            "exported_at": req.exported_at or datetime.now().isoformat(),
            "total_messages": len(req.transcripts),
            "transcripts": req.transcripts
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"[Sessions] Saved session '{req.session_id}' ({len(req.transcripts)} messages) to {filepath}")
        return {"status": "success", "session_id": req.session_id, "filepath": str(filepath)}
    except Exception as e:
        logger.error(f"[Sessions] Error saving session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save session transcript: {e}")


@router.get("/sessions/list")
async def list_saved_sessions():
    """List all archived session JSON files."""
    try:
        sessions = []
        for file in sorted(SESSIONS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sessions.append({
                        "session_id": data.get("session_id", file.stem),
                        "exported_at": data.get("exported_at", ""),
                        "total_messages": data.get("total_messages", len(data.get("transcripts", []))),
                        "filename": file.name
                    })
            except Exception:
                pass
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"[Sessions] Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list session transcripts: {e}")


@router.get("/sessions/{session_id}")
async def get_session_transcript(session_id: str):
    """Retrieve full JSON for a specific session."""
    clean_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")).strip()
    filepath = SESSIONS_DIR / f"{clean_id}.json"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Session transcript '{session_id}' not found.")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read session: {e}")


# ── Codebase-wide Permanent Conversations Storage (data/conversations.json) ──

class SyncConversationsRequest(BaseModel):
    conversations: List[Dict[str, Any]]


@router.get("/conversations")
async def get_all_conversations():
    """Retrieve all persistent conversation history from data/conversations.json."""
    return {
        "status": "success",
        "total_conversations": len(session_manager.get_all_transcripts()),
        "conversations": session_manager.get_all_transcripts()
    }


@router.post("/conversations/sync")
async def sync_all_conversations(req: SyncConversationsRequest):
    """Sync frontend transcripts with backend permanent conversations.json."""
    try:
        session_manager.set_all_transcripts(req.conversations)
        return {
            "status": "success",
            "total_conversations": len(req.conversations)
        }
    except Exception as e:
        logger.error(f"[Conversations] Sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/clear")
async def clear_all_conversations():
    """Clear all stored conversations."""
    try:
        session_manager.clear_all()
        return {"status": "success", "message": "All conversation history cleared."}
    except Exception as e:
        logger.error(f"[Conversations] Clear error: {e}")
        raise HTTPException(status_code=500, detail=str(e))




