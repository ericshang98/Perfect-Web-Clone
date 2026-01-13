"""
Checkpoint API Routes
检查点 API 路由

Provides HTTP endpoints for checkpoint operations:
- POST   /api/checkpoints/projects              - Create project
- GET    /api/checkpoints/projects              - List all projects
- GET    /api/checkpoints/projects/{id}         - Get project detail
- PATCH  /api/checkpoints/projects/{id}         - Update project
- DELETE /api/checkpoints/projects/{id}         - Delete project

- POST   /api/checkpoints/projects/{id}/save    - Save checkpoint
- GET    /api/checkpoints/projects/{id}/list    - List checkpoints
- GET    /api/checkpoints/projects/{id}/{cp_id} - Get checkpoint detail
- DELETE /api/checkpoints/projects/{id}/{cp_id} - Delete checkpoint

- POST   /api/checkpoints/clear-temp            - Clear temporary projects
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

from .checkpoint_store import checkpoint_store

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


# ============================================
# Request/Response Models
# ============================================

class CreateProjectRequest(BaseModel):
    """Request model for creating a project"""
    name: str = Field(..., description="Project name")
    description: str = Field("", description="Project description")
    source_id: Optional[str] = Field(None, description="Associated source ID")
    source_url: Optional[str] = Field(None, description="Source URL")
    thumbnail: Optional[str] = Field(None, description="Thumbnail path")
    is_showcase: bool = Field(False, description="Is showcase (permanent)")
    project_id: Optional[str] = Field(None, description="Custom project ID")


class UpdateProjectRequest(BaseModel):
    """Request model for updating a project"""
    name: Optional[str] = None
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    is_showcase: Optional[bool] = None


class SaveCheckpointRequest(BaseModel):
    """Request model for saving a checkpoint"""
    name: str = Field(..., description="Checkpoint name")
    conversation: List[Dict[str, Any]] = Field(..., description="Conversation history")
    files: Dict[str, str] = Field(..., description="File snapshots")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class ProjectSummary(BaseModel):
    """Project summary for list endpoint"""
    id: str
    name: str
    description: str
    source_url: Optional[str]
    thumbnail: Optional[str]
    is_showcase: bool
    created_at: str
    updated_at: str
    checkpoint_count: int


class CheckpointSummary(BaseModel):
    """Checkpoint summary for list endpoint"""
    id: str
    name: str
    timestamp: float
    created_at: str
    conversation_count: int
    files_count: int
    metadata: Dict[str, Any]


# ============================================
# Project Endpoints
# ============================================

@router.post("/projects")
async def create_project(request: CreateProjectRequest):
    """
    Create or get existing checkpoint project
    创建新的检查点项目或获取已存在的项目

    If source_id is provided and a project with that source_id already exists,
    returns the existing project instead of creating a new one.
    """
    try:
        # Use get_or_create to avoid duplicates when called multiple times
        project = checkpoint_store.get_or_create_project(
            name=request.name,
            description=request.description,
            source_id=request.source_id,
            source_url=request.source_url,
            thumbnail=request.thumbnail,
            is_showcase=request.is_showcase,
        )
        return {
            "success": True,
            "project": project.to_summary(),
            "message": f"Project ready: {project.id}",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def list_projects(include_temp: bool = True):
    """
    List all checkpoint projects
    列出所有检查点项目

    Args:
        include_temp: Include temporary (non-showcase) projects
    """
    projects = checkpoint_store.list_projects(include_temp=include_temp)
    return {
        "success": True,
        "count": len(projects),
        "projects": [p.to_summary() for p in projects],
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """
    Get project detail with checkpoint list
    获取项目详情及检查点列表
    """
    project = checkpoint_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    checkpoints = checkpoint_store.get_checkpoint_summaries(project_id)

    return {
        "success": True,
        "project": project.to_dict(),
        "checkpoints": checkpoints,
    }


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: UpdateProjectRequest):
    """
    Update project metadata
    更新项目元数据
    """
    project = checkpoint_store.update_project(
        project_id=project_id,
        name=request.name,
        description=request.description,
        thumbnail=request.thumbnail,
        is_showcase=request.is_showcase,
    )
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    return {
        "success": True,
        "project": project.to_summary(),
        "message": f"Updated project: {project_id}",
    }


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, force: bool = False):
    """
    Delete project and all checkpoints
    删除项目及所有检查点

    Args:
        force: Force delete even if is_showcase
    """
    project = checkpoint_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    if project.is_showcase and not force:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete showcase project. Use force=true to override."
        )

    if checkpoint_store.delete_project(project_id, force=force):
        return {
            "success": True,
            "message": f"Deleted project: {project_id}",
        }
    raise HTTPException(status_code=500, detail="Failed to delete project")


# ============================================
# Checkpoint Endpoints
# ============================================

@router.post("/projects/{project_id}/save")
async def save_checkpoint(project_id: str, request: SaveCheckpointRequest):
    """
    Save a new checkpoint to project
    保存新的检查点到项目
    """
    checkpoint = checkpoint_store.save_checkpoint(
        project_id=project_id,
        name=request.name,
        conversation=request.conversation,
        files=request.files,
        metadata=request.metadata,
    )
    if not checkpoint:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    return {
        "success": True,
        "checkpoint": checkpoint.to_summary(),
        "message": f"Saved checkpoint: {checkpoint.id}",
    }


@router.get("/projects/{project_id}/list")
async def list_checkpoints(project_id: str):
    """
    List all checkpoints in project
    列出项目中的所有检查点
    """
    project = checkpoint_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    checkpoints = checkpoint_store.get_checkpoint_summaries(project_id)
    return {
        "success": True,
        "project_id": project_id,
        "count": len(checkpoints),
        "checkpoints": checkpoints,
    }


@router.get("/projects/{project_id}/{checkpoint_id}")
async def get_checkpoint(project_id: str, checkpoint_id: str):
    """
    Get checkpoint detail with full data
    获取检查点详情（含完整数据）
    """
    checkpoint = checkpoint_store.get_checkpoint(project_id, checkpoint_id)
    if not checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint not found: {project_id}/{checkpoint_id}"
        )

    return {
        "success": True,
        "checkpoint": checkpoint.to_dict(),
    }


@router.delete("/projects/{project_id}/{checkpoint_id}")
async def delete_checkpoint(project_id: str, checkpoint_id: str):
    """
    Delete a checkpoint
    删除检查点
    """
    if checkpoint_store.delete_checkpoint(project_id, checkpoint_id):
        return {
            "success": True,
            "message": f"Deleted checkpoint: {checkpoint_id}",
        }
    raise HTTPException(
        status_code=404,
        detail=f"Checkpoint not found: {project_id}/{checkpoint_id}"
    )


# ============================================
# Utility Endpoints
# ============================================

@router.get("/all")
async def list_all_checkpoints():
    """
    List ALL checkpoints from ALL projects
    列出所有项目的所有检查点

    Returns checkpoints grouped by project, sorted by timestamp (newest first).
    """
    projects = checkpoint_store.list_projects(include_temp=True)
    all_checkpoints = []

    for project in projects:
        checkpoints = checkpoint_store.get_checkpoint_summaries(project.id)
        for cp in checkpoints:
            all_checkpoints.append({
                **cp,
                "project_id": project.id,
                "project_name": project.name,
                "source_url": project.source_url,
            })

    # Sort by timestamp (newest first)
    all_checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    return {
        "success": True,
        "count": len(all_checkpoints),
        "projects_count": len(projects),
        "checkpoints": all_checkpoints,
    }


@router.post("/clear-temp")
async def clear_temp_projects():
    """
    Clear all temporary (non-showcase) projects
    清除所有临时项目

    This is called on page refresh to clean up user session data
    while preserving showcase projects.
    """
    count = checkpoint_store.clear_temp_projects()
    return {
        "success": True,
        "message": f"Cleared {count} temporary projects",
        "deleted_count": count,
    }


@router.get("/showcases")
async def list_showcases():
    """
    List only showcase projects (for Gallery)
    只列出展示案例（用于 Gallery）
    """
    projects = checkpoint_store.list_projects(include_temp=False)
    return {
        "success": True,
        "count": len(projects),
        "showcases": [p.to_summary() for p in projects],
    }
