"use client";

import React, { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Clock,
  RefreshCw,
  Loader2,
  X,
  Trash2,
  Save,
  RotateCcw,
  MessageSquare,
  FileText,
  History,
  HardDrive,
  ChevronDown,
  ChevronRight,
  FolderOpen,
} from "lucide-react";

// ============================================
// Types
// ============================================

export interface CheckpointSummary {
  id: string;
  name: string;
  timestamp: number;
  created_at: string;
  conversation_count: number;
  files_count: number;
  total_size: number;  // Size in bytes
  metadata: Record<string, unknown>;
  // Added for all-checkpoints view
  project_id?: string;
  project_name?: string;
  source_url?: string | null;
}

// Format bytes to human readable
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  source_url: string | null;
  thumbnail: string | null;
  is_showcase: boolean;
  created_at: string;
  updated_at: string;
  checkpoint_count: number;
}

interface CheckpointPanelProps {
  projectId?: string | null;
  onRestoreCheckpoint?: (checkpointId: string, projectId: string) => void;
  onSaveCheckpoint?: () => void;
  disabled?: boolean;
  className?: string;
}

// API Base URL
const API_BASE = process.env.NEXT_PUBLIC_BOXLITE_API_URL || "http://localhost:5100";

// ============================================
// Checkpoint Card Component
// ============================================

function CheckpointCard({
  checkpoint,
  onRestore,
  onDelete,
  disabled = false,
  isDeleting = false,
  showProjectName = false,
}: {
  checkpoint: CheckpointSummary;
  onRestore: () => void;
  onDelete: () => void;
  disabled?: boolean;
  isDeleting?: boolean;
  showProjectName?: boolean;
}) {
  // Format date
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) {
      return "Just now";
    } else if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    } else if (diffDays === 1) {
      return "Yesterday";
    } else if (diffDays < 7) {
      return `${diffDays} days ago`;
    } else {
      return date.toLocaleDateString();
    }
  };

  // Handle delete click with confirmation
  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (
      window.confirm(
        `Delete "${checkpoint.name}"?\n\nThis will permanently remove this checkpoint.`
      )
    ) {
      onDelete();
    }
  };

  return (
    <div
      className={cn(
        "relative w-full text-left p-3 rounded-lg transition-all group",
        "border border-neutral-200 dark:border-neutral-700",
        (disabled || isDeleting) && "opacity-50 cursor-not-allowed",
        !disabled &&
          !isDeleting &&
          "hover:border-amber-300 dark:hover:border-amber-600 hover:shadow-sm"
      )}
    >
      {/* Delete button */}
      {!disabled && !isDeleting && (
        <button
          onClick={handleDelete}
          className={cn(
            "absolute top-2 right-2 p-1.5 rounded-md transition-all",
            "opacity-0 group-hover:opacity-100",
            "text-neutral-400 hover:text-red-500",
            "hover:bg-red-50 dark:hover:bg-red-900/20",
            "z-10"
          )}
          title="Delete checkpoint"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}

      {/* Deleting indicator */}
      {isDeleting && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/50 dark:bg-black/50 rounded-lg z-10">
          <Loader2 className="h-5 w-5 animate-spin text-red-500" />
        </div>
      )}

      {/* Content */}
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div
          className={cn(
            "flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center",
            "bg-amber-100 dark:bg-amber-900/40"
          )}
        >
          <History className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        </div>
        <div className="flex-1 min-w-0 pr-6">
          <h4 className="text-sm font-medium text-neutral-900 dark:text-white truncate">
            {checkpoint.name}
          </h4>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            {formatDate(checkpoint.created_at)}
          </p>
        </div>
      </div>

      {/* Meta info */}
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mt-2 text-xs text-neutral-500 dark:text-neutral-400">
        <span className="flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          {checkpoint.conversation_count} msgs
        </span>
        <span className="flex items-center gap-1">
          <FileText className="h-3 w-3" />
          {checkpoint.files_count} files
        </span>
        <span className="flex items-center gap-1">
          <HardDrive className="h-3 w-3" />
          {formatBytes(checkpoint.total_size || 0)}
        </span>
      </div>

      {/* Restore button */}
      {!disabled && !isDeleting && (
        <button
          onClick={onRestore}
          className={cn(
            "mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
            "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400",
            "hover:bg-amber-100 dark:hover:bg-amber-900/40"
          )}
        >
          <RotateCcw className="h-3 w-3" />
          Restore
        </button>
      )}
    </div>
  );
}

// ============================================
// Project Group Component
// ============================================

function ProjectGroup({
  projectId,
  projectName,
  checkpoints,
  onRestore,
  onDelete,
  disabled,
  deletingCheckpointId,
  defaultExpanded = true,
}: {
  projectId: string;
  projectName: string;
  checkpoints: CheckpointSummary[];
  onRestore: (checkpointId: string, projectId: string) => void;
  onDelete: (checkpointId: string, projectId: string) => void;
  disabled: boolean;
  deletingCheckpointId: string | null;
  defaultExpanded?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="mb-4">
      {/* Project Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={cn(
          "w-full flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors",
          "hover:bg-neutral-100 dark:hover:bg-neutral-800",
          "text-left"
        )}
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-neutral-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-neutral-400" />
        )}
        <FolderOpen className="h-4 w-4 text-amber-500" />
        <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300 truncate flex-1">
          {projectName}
        </span>
        <span className="text-xs text-neutral-400">
          {checkpoints.length}
        </span>
      </button>

      {/* Checkpoints */}
      {isExpanded && (
        <div className="ml-6 mt-2 space-y-2">
          {checkpoints.map((checkpoint) => (
            <CheckpointCard
              key={checkpoint.id}
              checkpoint={checkpoint}
              onRestore={() => onRestore(checkpoint.id, projectId)}
              onDelete={() => onDelete(checkpoint.id, projectId)}
              disabled={disabled}
              isDeleting={deletingCheckpointId === checkpoint.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// Main Checkpoint Panel Component
// ============================================

export function CheckpointPanel({
  projectId = null,
  onRestoreCheckpoint,
  onSaveCheckpoint,
  disabled = false,
  className,
}: CheckpointPanelProps) {
  const [checkpoints, setCheckpoints] = useState<CheckpointSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingCheckpointId, setDeletingCheckpointId] = useState<string | null>(null);

  // Fetch ALL checkpoints from ALL projects
  const fetchCheckpoints = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      // Always fetch all checkpoints
      const response = await fetch(`${API_BASE}/api/checkpoints/all`);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      if (data.success) {
        setCheckpoints(data.checkpoints || []);
      } else {
        throw new Error(data.error || "Failed to fetch checkpoints");
      }
    } catch (err) {
      console.error("Failed to fetch checkpoints:", err);
      setError(err instanceof Error ? err.message : "Failed to load checkpoints");
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Load checkpoints on mount
  useEffect(() => {
    fetchCheckpoints();
  }, [fetchCheckpoints]);

  // Group checkpoints by project
  const groupedCheckpoints = React.useMemo(() => {
    const groups: Record<string, { name: string; checkpoints: CheckpointSummary[] }> = {};

    for (const cp of checkpoints) {
      const pid = cp.project_id || "unknown";
      const pname = cp.project_name || "Unknown Project";

      if (!groups[pid]) {
        groups[pid] = { name: pname, checkpoints: [] };
      }
      groups[pid].checkpoints.push(cp);
    }

    return groups;
  }, [checkpoints]);

  // Handle checkpoint deletion
  const handleDeleteCheckpoint = useCallback(
    async (checkpointId: string, cpProjectId: string) => {
      setDeletingCheckpointId(checkpointId);

      try {
        const response = await fetch(
          `${API_BASE}/api/checkpoints/projects/${cpProjectId}/${checkpointId}`,
          { method: "DELETE" }
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail || `HTTP error! status: ${response.status}`
          );
        }

        // Remove from local state
        setCheckpoints((prev) => prev.filter((c) => c.id !== checkpointId));
      } catch (err) {
        console.error("Failed to delete checkpoint:", err);
        alert(err instanceof Error ? err.message : "Failed to delete checkpoint");
      } finally {
        setDeletingCheckpointId(null);
      }
    },
    []
  );

  // Handle restore
  const handleRestore = (checkpointId: string, cpProjectId: string) => {
    onRestoreCheckpoint?.(checkpointId, cpProjectId);
  };

  const totalCheckpoints = checkpoints.length;
  const projectCount = Object.keys(groupedCheckpoints).length;

  return (
    <div
      className={cn(
        "flex flex-col h-full",
        "bg-white dark:bg-neutral-900",
        "border-l border-neutral-200 dark:border-neutral-700",
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center justify-between px-4 py-3 flex-shrink-0",
          "border-b border-neutral-200 dark:border-neutral-700"
        )}
      >
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-900/40 flex items-center justify-center">
            <History className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-white">
              Checkpoints
            </h2>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              {totalCheckpoints} saved in {projectCount} project{projectCount !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {/* Add Checkpoint Button */}
          {onSaveCheckpoint && projectId && (
            <button
              onClick={onSaveCheckpoint}
              disabled={disabled}
              title="Save checkpoint"
              className={cn(
                "p-2 rounded-lg transition-colors",
                "text-amber-600 dark:text-amber-400",
                "hover:bg-amber-100 dark:hover:bg-amber-900/40",
                "disabled:opacity-50"
              )}
            >
              <Save className="h-4 w-4" />
            </button>
          )}
          {/* Refresh Button */}
          <button
            onClick={fetchCheckpoints}
            disabled={isLoading}
            title="Refresh checkpoints"
            className={cn(
              "p-2 rounded-lg transition-colors",
              "text-neutral-500 dark:text-neutral-400",
              "hover:bg-neutral-100 dark:hover:bg-neutral-800",
              "disabled:opacity-50"
            )}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {/* Save Checkpoint Button */}
      {onSaveCheckpoint && projectId && (
        <div className="px-3 py-2 border-b border-neutral-200 dark:border-neutral-700">
          <button
            onClick={onSaveCheckpoint}
            disabled={disabled}
            className={cn(
              "w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              "bg-amber-500 text-white",
              "hover:bg-amber-600",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            <Save className="h-4 w-4" />
            Save Checkpoint
          </button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">
        {isLoading && checkpoints.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Loader2 className="h-8 w-8 animate-spin text-neutral-400 mb-2" />
            <p className="text-sm text-neutral-500 dark:text-neutral-400">
              Loading checkpoints...
            </p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-4">
            <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center mb-3">
              <X className="h-6 w-6 text-red-500" />
            </div>
            <p className="text-sm text-neutral-600 dark:text-neutral-400 mb-3">
              {error}
            </p>
            <button
              onClick={fetchCheckpoints}
              className={cn(
                "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                "bg-neutral-100 dark:bg-neutral-800",
                "text-neutral-700 dark:text-neutral-300",
                "hover:bg-neutral-200 dark:hover:bg-neutral-700"
              )}
            >
              Try Again
            </button>
          </div>
        ) : checkpoints.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-4">
            <div className="w-12 h-12 rounded-full bg-neutral-100 dark:bg-neutral-800 flex items-center justify-center mb-3">
              <History className="h-6 w-6 text-neutral-400" />
            </div>
            <h3 className="text-sm font-medium text-neutral-900 dark:text-white mb-1">
              No checkpoints yet
            </h3>
            <p className="text-xs text-neutral-500 dark:text-neutral-400">
              Save a checkpoint to capture the current state of your project.
            </p>
          </div>
        ) : (
          <div>
            {Object.entries(groupedCheckpoints).map(([pid, group]) => (
              <ProjectGroup
                key={pid}
                projectId={pid}
                projectName={group.name}
                checkpoints={group.checkpoints}
                onRestore={handleRestore}
                onDelete={handleDeleteCheckpoint}
                disabled={disabled}
                deletingCheckpointId={deletingCheckpointId}
                defaultExpanded={true}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      {checkpoints.length > 0 && (
        <div
          className={cn(
            "flex-shrink-0 px-4 py-2",
            "border-t border-neutral-200 dark:border-neutral-700",
            "bg-neutral-50 dark:bg-neutral-800/50"
          )}
        >
          <p className="text-xs text-neutral-500 dark:text-neutral-400">
            Click "Restore" to return to a previous state.
          </p>
        </div>
      )}
    </div>
  );
}
