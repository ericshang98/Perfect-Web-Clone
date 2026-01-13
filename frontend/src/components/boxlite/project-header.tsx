"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Bot, Database, Settings, History } from "lucide-react";

/**
 * Project Header Props
 */
interface ProjectHeaderProps {
  projectName: string;
  showChatPanel: boolean;
  onToggleChatPanel: () => void;
  showSourcePanel: boolean;
  onToggleSourcePanel: () => void;
  showCheckpointPanel: boolean;
  onToggleCheckpointPanel: () => void;
  status?: "idle" | "ready" | "booting" | "error";
}

/**
 * Project Header Component
 * 顶部栏，包含项目名称和控制按钮
 */
export function ProjectHeader({
  projectName,
  showChatPanel,
  onToggleChatPanel,
  showSourcePanel,
  onToggleSourcePanel,
  showCheckpointPanel,
  onToggleCheckpointPanel,
  status = "idle",
}: ProjectHeaderProps) {
  // Status indicator colors
  const statusColors: Record<string, string> = {
    booting: "bg-yellow-500",
    ready: "bg-green-500",
    error: "bg-red-500",
    idle: "bg-neutral-400",
  };

  const statusLabels: Record<string, string> = {
    booting: "Starting...",
    ready: "Ready",
    error: "Error",
    idle: "Idle",
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between px-4 py-1.5 flex-shrink-0",
        "border-b border-neutral-200 dark:border-neutral-700",
        "bg-white dark:bg-neutral-900"
      )}
    >
      {/* Left: Project Name + Status */}
      <div className="flex items-center gap-3">
        {/* Project Name (read-only, set by AI) */}
        {projectName && (
          <span
            className={cn(
              "px-2 py-1 text-sm font-medium",
              "text-neutral-900 dark:text-white"
            )}
          >
            {projectName}
          </span>
        )}

        {/* Status Indicator */}
        <div className="flex items-center gap-1.5 text-xs text-neutral-500 dark:text-neutral-400">
          <span className={cn("w-2 h-2 rounded-full", statusColors[status])} />
          <span>{statusLabels[status]}</span>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {/* Toggle Source Panel */}
        <button
          onClick={onToggleSourcePanel}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            showSourcePanel
              ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400"
              : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          )}
        >
          <Database className="h-4 w-4" />
          Sources
        </button>

        {/* Toggle Checkpoint Panel */}
        <button
          onClick={onToggleCheckpointPanel}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            showCheckpointPanel
              ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400"
              : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          )}
        >
          <History className="h-4 w-4" />
          Checkpoints
        </button>

        {/* Toggle Chat Panel */}
        <button
          onClick={onToggleChatPanel}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            showChatPanel
              ? "bg-neutral-200 dark:bg-neutral-700 text-neutral-800 dark:text-neutral-200"
              : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          )}
        >
          <Bot className="h-4 w-4" />
          AI Assistant
        </button>

        {/* Settings */}
        <button
          className={cn(
            "p-2 rounded-lg transition-colors",
            "text-neutral-500 dark:text-neutral-400",
            "hover:bg-neutral-100 dark:hover:bg-neutral-800"
          )}
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
