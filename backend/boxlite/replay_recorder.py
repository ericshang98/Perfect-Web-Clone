"""
Replay Recorder for BoxLite Agent

Records agent execution events for later playback in the Gallery.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ReplayEvent:
    """Base class for replay events"""
    type: str
    timestamp: int  # ms since recording start

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentThinkingEvent(ReplayEvent):
    content: str

    def __init__(self, timestamp: int, content: str):
        super().__init__(type="agent_thinking", timestamp=timestamp)
        self.content = content


@dataclass
class ToolCallEvent(ReplayEvent):
    tool_name: str
    tool_input: Dict[str, Any]

    def __init__(self, timestamp: int, tool_name: str, tool_input: Dict[str, Any]):
        super().__init__(type="tool_call", timestamp=timestamp)
        self.tool_name = tool_name
        self.tool_input = tool_input


@dataclass
class ToolResultEvent(ReplayEvent):
    tool_name: str
    success: bool
    result: str

    def __init__(self, timestamp: int, tool_name: str, success: bool, result: str):
        super().__init__(type="tool_result", timestamp=timestamp)
        self.tool_name = tool_name
        self.success = success
        self.result = result[:2000]  # Truncate long results


@dataclass
class WorkerSpawnedEvent(ReplayEvent):
    workers: List[Dict[str, str]]

    def __init__(self, timestamp: int, workers: List[Dict[str, str]]):
        super().__init__(type="worker_spawned", timestamp=timestamp)
        self.workers = workers


@dataclass
class WorkerProgressEvent(ReplayEvent):
    worker_id: str
    section_name: str
    status: str  # started, completed, failed
    file_path: Optional[str] = None

    def __init__(self, timestamp: int, worker_id: str, section_name: str,
                 status: str, file_path: Optional[str] = None):
        super().__init__(type="worker_progress", timestamp=timestamp)
        self.worker_id = worker_id
        self.section_name = section_name
        self.status = status
        self.file_path = file_path


@dataclass
class FileWrittenEvent(ReplayEvent):
    path: str
    content: str
    size: int

    def __init__(self, timestamp: int, path: str, content: str):
        super().__init__(type="file_written", timestamp=timestamp)
        self.path = path
        self.content = content
        self.size = len(content)


@dataclass
class PreviewReadyEvent(ReplayEvent):
    url: str

    def __init__(self, timestamp: int, url: str):
        super().__init__(type="preview_ready", timestamp=timestamp)
        self.url = url


class ReplayRecorder:
    """
    Records agent execution events for showcase playback.

    Usage:
        recorder = ReplayRecorder()
        recorder.start()

        # During agent execution:
        recorder.record_thinking("Analyzing the page...")
        recorder.record_tool_call("get_layout", {"source_id": "xxx"})
        recorder.record_file_written("/src/App.jsx", content)

        # After completion:
        replay_data = recorder.export()
        recorder.save_to_file("showcases/stripe/replay.json")
    """

    def __init__(self):
        self.events: List[ReplayEvent] = []
        self.start_time: Optional[float] = None
        self.is_recording: bool = False
        self.files_snapshot: Dict[str, str] = {}

    def start(self):
        """Start recording"""
        self.events = []
        self.start_time = time.time()
        self.is_recording = True
        self.files_snapshot = {}
        logger.info("[ReplayRecorder] Recording started")

    def stop(self):
        """Stop recording"""
        self.is_recording = False
        logger.info(f"[ReplayRecorder] Recording stopped. {len(self.events)} events recorded")

    def _get_timestamp(self) -> int:
        """Get milliseconds since recording started"""
        if self.start_time is None:
            return 0
        return int((time.time() - self.start_time) * 1000)

    def _add_event(self, event: ReplayEvent):
        """Add event to recording"""
        if not self.is_recording:
            return
        self.events.append(event)

    # ============================================
    # Recording Methods
    # ============================================

    def record_thinking(self, content: str):
        """Record agent thinking/text output"""
        self._add_event(AgentThinkingEvent(
            timestamp=self._get_timestamp(),
            content=content
        ))

    def record_tool_call(self, tool_name: str, tool_input: Dict[str, Any]):
        """Record tool call"""
        # Sanitize large inputs
        sanitized_input = self._sanitize_input(tool_input)
        self._add_event(ToolCallEvent(
            timestamp=self._get_timestamp(),
            tool_name=tool_name,
            tool_input=sanitized_input
        ))

    def record_tool_result(self, tool_name: str, success: bool, result: str):
        """Record tool result"""
        self._add_event(ToolResultEvent(
            timestamp=self._get_timestamp(),
            tool_name=tool_name,
            success=success,
            result=result
        ))

    def record_workers_spawned(self, workers: List[Dict[str, str]]):
        """Record worker spawn event"""
        self._add_event(WorkerSpawnedEvent(
            timestamp=self._get_timestamp(),
            workers=workers
        ))

    def record_worker_progress(self, worker_id: str, section_name: str,
                                status: str, file_path: Optional[str] = None):
        """Record worker progress"""
        self._add_event(WorkerProgressEvent(
            timestamp=self._get_timestamp(),
            worker_id=worker_id,
            section_name=section_name,
            status=status,
            file_path=file_path
        ))

    def record_file_written(self, path: str, content: str):
        """Record file write and update snapshot"""
        self._add_event(FileWrittenEvent(
            timestamp=self._get_timestamp(),
            path=path,
            content=content
        ))
        # Update files snapshot
        self.files_snapshot[path] = content

    def record_preview_ready(self, url: str):
        """Record preview ready event"""
        self._add_event(PreviewReadyEvent(
            timestamp=self._get_timestamp(),
            url=url
        ))

    # ============================================
    # Export Methods
    # ============================================

    def _sanitize_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize large input data for storage"""
        result = {}
        for key, value in input_data.items():
            if isinstance(value, str) and len(value) > 500:
                result[key] = value[:500] + f"... ({len(value)} chars)"
            elif isinstance(value, dict):
                result[key] = self._sanitize_input(value)
            elif isinstance(value, list) and len(value) > 10:
                result[key] = value[:10] + [f"... ({len(value)} items)"]
            else:
                result[key] = value
        return result

    def export_replay(self) -> Dict[str, Any]:
        """Export replay data"""
        total_duration = self._get_timestamp() if self.start_time else 0

        return {
            "version": "1.0",
            "recorded_at": datetime.now().isoformat(),
            "events": [e.to_dict() for e in self.events],
            "total_duration_ms": total_duration
        }

    def export_files(self) -> Dict[str, Any]:
        """Export final files snapshot"""
        return {
            "files": self.files_snapshot
        }

    def export_meta(self, name: str, description: str, source_url: str,
                    preview_image: str, showcase_id: str) -> Dict[str, Any]:
        """Export metadata"""
        total_duration = self._get_timestamp() if self.start_time else 0

        # Count stats
        file_events = [e for e in self.events if e.type == "file_written"]
        worker_events = [e for e in self.events if e.type == "worker_spawned"]
        section_count = 0
        if worker_events:
            section_count = len(worker_events[0].workers) if hasattr(worker_events[0], 'workers') else 0

        return {
            "id": showcase_id,
            "name": name,
            "description": description,
            "source_url": source_url,
            "preview_image": preview_image,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "stats": {
                "sections": section_count,
                "files": len(file_events),
                "duration_seconds": total_duration // 1000
            }
        }

    def save_to_directory(self, directory: Path, name: str, description: str,
                          source_url: str, showcase_id: str):
        """
        Save all showcase data to a directory.

        Creates:
        - meta.json
        - replay.json
        - files.json
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        preview_image = f"/showcases/{showcase_id}/preview.png"

        # Save meta
        meta = self.export_meta(name, description, source_url, preview_image, showcase_id)
        with open(directory / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Save replay
        replay = self.export_replay()
        with open(directory / "replay.json", "w", encoding="utf-8") as f:
            json.dump(replay, f, indent=2, ensure_ascii=False)

        # Save files
        files = self.export_files()
        with open(directory / "files.json", "w", encoding="utf-8") as f:
            json.dump(files, f, indent=2, ensure_ascii=False)

        logger.info(f"[ReplayRecorder] Saved showcase to {directory}")
        logger.info(f"  - {len(self.events)} events")
        logger.info(f"  - {len(self.files_snapshot)} files")

        return {
            "meta": meta,
            "replay": replay,
            "files": files
        }


# Global recorder instance (optional, for easy access)
_global_recorder: Optional[ReplayRecorder] = None


def get_recorder() -> Optional[ReplayRecorder]:
    """Get the global recorder instance"""
    return _global_recorder


def start_recording() -> ReplayRecorder:
    """Start a new recording session"""
    global _global_recorder
    _global_recorder = ReplayRecorder()
    _global_recorder.start()
    return _global_recorder


def stop_recording() -> Optional[ReplayRecorder]:
    """Stop and return the current recording"""
    global _global_recorder
    if _global_recorder:
        _global_recorder.stop()
    return _global_recorder
