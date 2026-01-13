"""
Checkpoint Store Implementation
检查点存储实现

File-based storage for project checkpoints.
Each project has its own directory with manifest and checkpoint files.

Features:
- Project-based organization
- Full file snapshots for code rollback
- Conversation history preservation
- Showcase marking for permanent retention
"""

import os
import json
import time
import uuid
import shutil
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Default data directory
DATA_DIR = Path(__file__).parent.parent / "data" / "checkpoints"


@dataclass
class Checkpoint:
    """
    Single checkpoint data structure
    单个检查点数据结构
    """
    id: str
    name: str
    timestamp: float
    conversation: List[Dict[str, Any]]  # 对话记录
    files: Dict[str, str]               # 文件快照 {path: content}
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def created_at(self) -> str:
        """Get ISO format creation time"""
        return datetime.fromtimestamp(self.timestamp).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
            "conversation": self.conversation,
            "files": self.files,
            "metadata": self.metadata,
        }

    def to_summary(self) -> Dict[str, Any]:
        """Convert to summary (without full data)"""
        # Calculate total size of all files
        total_size = sum(len(content.encode('utf-8')) for content in self.files.values())

        return {
            "id": self.id,
            "name": self.name,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
            "conversation_count": len(self.conversation),
            "files_count": len(self.files),
            "total_size": total_size,  # Total size in bytes
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        """Create from dict"""
        return cls(
            id=data["id"],
            name=data["name"],
            timestamp=data["timestamp"],
            conversation=data.get("conversation", []),
            files=data.get("files", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CheckpointProject:
    """
    Project containing multiple checkpoints
    包含多个检查点的项目
    """
    id: str
    name: str
    description: str
    source_id: Optional[str]            # 关联的 source
    source_url: Optional[str]           # 源 URL
    thumbnail: Optional[str]            # Gallery 缩略图路径
    is_showcase: bool                   # 是否为展示案例（永久保留）
    created_at: float
    updated_at: float
    checkpoints: List[str]              # checkpoint IDs
    current_checkpoint: Optional[str]   # 当前 checkpoint ID

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "thumbnail": self.thumbnail,
            "is_showcase": self.is_showcase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "checkpoints": self.checkpoints,
            "current_checkpoint": self.current_checkpoint,
        }

    def to_summary(self) -> Dict[str, Any]:
        """Convert to summary for list endpoint"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_url": self.source_url,
            "thumbnail": self.thumbnail,
            "is_showcase": self.is_showcase,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
            "checkpoint_count": len(self.checkpoints),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointProject":
        """Create from dict"""
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            source_id=data.get("source_id"),
            source_url=data.get("source_url"),
            thumbnail=data.get("thumbnail"),
            is_showcase=data.get("is_showcase", False),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            checkpoints=data.get("checkpoints", []),
            current_checkpoint=data.get("current_checkpoint"),
        )


class CheckpointStore:
    """
    File-based checkpoint storage
    基于文件的检查点存储

    Directory structure:
    /data/checkpoints/
    ├── project-id-1/
    │   ├── manifest.json
    │   ├── cp_001.json
    │   └── cp_002.json
    └── project-id-2/
        └── ...
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize checkpoint store

        Args:
            data_dir: Directory for checkpoint storage
        """
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Checkpoint store initialized at: {self.data_dir}")

    # ============================================
    # Project Operations
    # ============================================

    def create_project(
        self,
        name: str,
        description: str = "",
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
        thumbnail: Optional[str] = None,
        is_showcase: bool = False,
        project_id: Optional[str] = None,
    ) -> CheckpointProject:
        """
        Create a new checkpoint project
        创建新的检查点项目

        Args:
            name: Project name
            description: Project description
            source_id: Associated source ID
            source_url: Source URL
            thumbnail: Thumbnail image path
            is_showcase: Whether this is a showcase (permanent)
            project_id: Optional custom project ID

        Returns:
            Created CheckpointProject
        """
        # Generate ID
        if project_id:
            pid = project_id
        else:
            # Create slug from name
            slug = name.lower().replace(" ", "-")[:30]
            pid = f"{slug}-{str(uuid.uuid4())[:8]}"

        now = time.time()
        project = CheckpointProject(
            id=pid,
            name=name,
            description=description,
            source_id=source_id,
            source_url=source_url,
            thumbnail=thumbnail,
            is_showcase=is_showcase,
            created_at=now,
            updated_at=now,
            checkpoints=[],
            current_checkpoint=None,
        )

        # Create project directory
        project_dir = self.data_dir / pid
        project_dir.mkdir(exist_ok=True)

        # Save manifest
        self._save_manifest(project)

        logger.info(f"Created checkpoint project: {pid}")
        return project

    def get_project(self, project_id: str) -> Optional[CheckpointProject]:
        """
        Get project by ID
        根据 ID 获取项目
        """
        manifest_path = self.data_dir / project_id / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CheckpointProject.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load project {project_id}: {e}")
            return None

    def list_projects(self, include_temp: bool = True) -> List[CheckpointProject]:
        """
        List all projects
        列出所有项目

        Args:
            include_temp: Include non-showcase (temporary) projects

        Returns:
            List of projects, sorted by updated_at (newest first)
        """
        projects = []
        for item in self.data_dir.iterdir():
            if item.is_dir():
                project = self.get_project(item.name)
                if project:
                    if include_temp or project.is_showcase:
                        projects.append(project)

        return sorted(projects, key=lambda p: -p.updated_at)

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        thumbnail: Optional[str] = None,
        is_showcase: Optional[bool] = None,
    ) -> Optional[CheckpointProject]:
        """
        Update project metadata
        更新项目元数据
        """
        project = self.get_project(project_id)
        if not project:
            return None

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if thumbnail is not None:
            project.thumbnail = thumbnail
        if is_showcase is not None:
            project.is_showcase = is_showcase

        project.updated_at = time.time()
        self._save_manifest(project)

        return project

    def delete_project(self, project_id: str, force: bool = False) -> bool:
        """
        Delete project and all its checkpoints
        删除项目及其所有检查点

        Args:
            project_id: Project ID
            force: Force delete even if is_showcase

        Returns:
            True if deleted
        """
        project = self.get_project(project_id)
        if not project:
            return False

        # Protect showcase projects
        if project.is_showcase and not force:
            logger.warning(f"Cannot delete showcase project: {project_id}")
            return False

        # Delete directory
        project_dir = self.data_dir / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)
            logger.info(f"Deleted project: {project_id}")
            return True

        return False

    def clear_temp_projects(self) -> int:
        """
        Clear all non-showcase (temporary) projects
        清除所有临时项目

        Returns:
            Number of projects deleted
        """
        count = 0
        for project in self.list_projects(include_temp=True):
            if not project.is_showcase:
                if self.delete_project(project.id, force=True):
                    count += 1
        logger.info(f"Cleared {count} temporary projects")
        return count

    # ============================================
    # Checkpoint Operations
    # ============================================

    def save_checkpoint(
        self,
        project_id: str,
        name: str,
        conversation: List[Dict[str, Any]],
        files: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Checkpoint]:
        """
        Save a new checkpoint to project
        保存新的检查点到项目

        Args:
            project_id: Project ID
            name: Checkpoint name
            conversation: Conversation history
            files: File snapshots {path: content}
            metadata: Additional metadata

        Returns:
            Created Checkpoint, or None if project not found
        """
        project = self.get_project(project_id)
        if not project:
            logger.error(f"Project not found: {project_id}")
            return None

        # Generate checkpoint ID
        cp_num = len(project.checkpoints) + 1
        cp_id = f"cp_{cp_num:03d}"

        checkpoint = Checkpoint(
            id=cp_id,
            name=name,
            timestamp=time.time(),
            conversation=conversation,
            files=files,
            metadata=metadata or {},
        )

        # Save checkpoint file
        cp_path = self.data_dir / project_id / f"{cp_id}.json"
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, ensure_ascii=False, indent=2)

        # Update project
        project.checkpoints.append(cp_id)
        project.current_checkpoint = cp_id
        project.updated_at = time.time()
        self._save_manifest(project)

        logger.info(f"Saved checkpoint {cp_id} to project {project_id}")
        return checkpoint

    def get_checkpoint(
        self,
        project_id: str,
        checkpoint_id: str,
    ) -> Optional[Checkpoint]:
        """
        Get checkpoint by ID
        根据 ID 获取检查点
        """
        cp_path = self.data_dir / project_id / f"{checkpoint_id}.json"
        if not cp_path.exists():
            return None

        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Checkpoint.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint {checkpoint_id}: {e}")
            return None

    def list_checkpoints(self, project_id: str) -> List[Checkpoint]:
        """
        List all checkpoints in project
        列出项目中的所有检查点

        Returns:
            List of checkpoints, sorted by timestamp
        """
        project = self.get_project(project_id)
        if not project:
            return []

        checkpoints = []
        for cp_id in project.checkpoints:
            cp = self.get_checkpoint(project_id, cp_id)
            if cp:
                checkpoints.append(cp)

        return sorted(checkpoints, key=lambda c: c.timestamp)

    def get_checkpoint_summaries(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Get checkpoint summaries (without full data)
        获取检查点摘要（不含完整数据）
        """
        checkpoints = self.list_checkpoints(project_id)
        return [cp.to_summary() for cp in checkpoints]

    def delete_checkpoint(
        self,
        project_id: str,
        checkpoint_id: str,
    ) -> bool:
        """
        Delete a checkpoint
        删除检查点
        """
        project = self.get_project(project_id)
        if not project or checkpoint_id not in project.checkpoints:
            return False

        # Delete file
        cp_path = self.data_dir / project_id / f"{checkpoint_id}.json"
        if cp_path.exists():
            cp_path.unlink()

        # Update project
        project.checkpoints.remove(checkpoint_id)
        if project.current_checkpoint == checkpoint_id:
            project.current_checkpoint = (
                project.checkpoints[-1] if project.checkpoints else None
            )
        project.updated_at = time.time()
        self._save_manifest(project)

        logger.info(f"Deleted checkpoint {checkpoint_id} from project {project_id}")
        return True

    # ============================================
    # Helper Methods
    # ============================================

    def _save_manifest(self, project: CheckpointProject):
        """Save project manifest to file"""
        manifest_path = self.data_dir / project.id / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)

    def get_or_create_project(
        self,
        name: str,
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
        **kwargs,
    ) -> CheckpointProject:
        """
        Get existing project or create new one
        获取现有项目或创建新项目

        Useful for auto-save scenarios.
        """
        # Try to find by source_id first
        if source_id:
            for project in self.list_projects():
                if project.source_id == source_id:
                    return project

        # Create new project
        return self.create_project(
            name=name,
            source_id=source_id,
            source_url=source_url,
            **kwargs,
        )


# Global singleton instance
checkpoint_store = CheckpointStore()
