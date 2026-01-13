"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  Loader2,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  Check,
  X,
  AlertCircle,
  Wifi,
  WifiOff,
  Settings2,
  FileText,
  Pencil,
  Trash2,
  Play,
  Package,
  Eye,
  Search,
  ArrowUp,
  Plus,
  ImageIcon,
} from "lucide-react";
import type {
  ChatMessage,
  WebContainerAction,
  WebContainerState,
  ToolCall,
  ContentBlock,
} from "@/types/nexting-agent";
import {
  createClient,
  NextingAgentClient,
  type ExecuteActionRequest,
  type WorkerSpawnedPayload,
  type WorkerToolCallPayload,
  type WorkerToolResultPayload,
  type WorkerCompletedPayload,
  type WorkerErrorPayload,
  type WorkerIterationPayload,
  type WorkerTextDeltaPayload,
} from "@/lib/api/nexting-agent";
import {
  createBoxLiteAgentClient,
  BoxLiteAgentClient,
  type WorkerSpawnedPayload as BoxLiteWorkerSpawnedPayload,
  type WorkerToolCallPayload as BoxLiteWorkerToolCallPayload,
  type WorkerToolResultPayload as BoxLiteWorkerToolResultPayload,
  type WorkerCompletedPayload as BoxLiteWorkerCompletedPayload,
  type WorkerErrorPayload as BoxLiteWorkerErrorPayload,
  type WorkerIterationPayload as BoxLiteWorkerIterationPayload,
  type WorkerTextDeltaPayload as BoxLiteWorkerTextDeltaPayload,
} from "@/lib/api/boxlite-agent";
import type { BoxLiteSandboxState } from "@/types/boxlite";
import { adaptBoxLiteState } from "@/lib/adapters/boxlite-state-adapter";
import {
  syncWorkerFileWrite,
  type FileSyncOptions,
} from "@/lib/worker-file-sync";
import { isActionError } from "@/hooks/use-webcontainer";
import { generateProjectName } from "@/lib/api/project-naming";

// ============================================
// Types
// ============================================

// Worker Agent state tracking
interface WorkerToolHistory {
  tool_name: string;
  status: "executing" | "success" | "error";
  input?: Record<string, unknown>;  // Tool input for debugging
  result?: string;                   // Tool result
}

interface WorkerState {
  worker_id: string;
  section_name: string;
  display_name?: string;  // Human-friendly name (e.g., "Navigation", "Section 1")
  status: "spawned" | "started" | "running" | "completed" | "error";
  task_description?: string;
  current_tool?: string;
  tool_history: WorkerToolHistory[];
  files: string[];
  summary?: string;
  error?: string;
  // Iteration tracking (NEW)
  iteration?: number;
  max_iterations?: number;
  // Reasoning text from worker (NEW)
  reasoning_text?: string;
  // Data size info
  input_data?: {
    html_lines?: number;
    html_chars?: number;
    html_range?: { start: number; end: number } | null;
    char_start?: number;
    char_end?: number;
    images_count?: number;
    links_count?: number;
    estimated_tokens?: number;
  };
}

/** Selected source info for display */
interface SelectedSource {
  id: string;
  title: string;
  url: string;
}

/**
 * Agent execution mode:
 * - "webcontainer": Uses WebContainer in browser (default, connects to nexting-agent backend)
 * - "boxlite": Uses BoxLite backend sandbox (connects to boxlite-agent backend)
 */
type AgentMode = "webcontainer" | "boxlite";

interface NextingAgentChatPanelProps {
  onWebContainerAction?: (action: WebContainerAction) => Promise<string>;
  getWebContainerState?: () => WebContainerState;
  messages: ChatMessage[];
  onMessagesChange: (messages: ChatMessage[]) => void;
  /** Selected source info from the source panel */
  selectedSource?: SelectedSource | null;
  /** Callback to clear selected source */
  onClearSource?: () => void;
  /** Callback when loading state changes (for disabling source selection) */
  onLoadingChange?: (isLoading: boolean) => void;
  /** Callback to clear file diffs when user sends a new message */
  onClearFileDiffs?: () => void;
  className?: string;
  /**
   * Agent execution mode (default: "webcontainer")
   * - "webcontainer": Tools execute in browser via WebContainer
   * - "boxlite": Tools execute on backend via BoxLite sandbox
   */
  mode?: AgentMode;
  /**
   * BoxLite sandbox ID (required when mode="boxlite")
   */
  sandboxId?: string;
  /**
   * BoxLite state (for boxlite mode)
   */
  boxliteState?: BoxLiteSandboxState | null;
  /**
   * Callback when BoxLite state updates (for boxlite mode)
   */
  onBoxLiteStateUpdate?: (state: BoxLiteSandboxState) => void;
  /**
   * Callback when project name is generated (for auto-naming)
   */
  onProjectNameGenerated?: (name: string) => void;
  /**
   * Auto-send a message on mount (for auto-clone flow)
   */
  autoSendMessage?: string;
  /**
   * Whether to trigger auto-send (controlled externally)
   */
  shouldAutoSend?: boolean;
  /**
   * Callback when auto-send is complete
   */
  onAutoSendComplete?: () => void;
  /**
   * Callback when backend triggers checkpoint save (frontend has full conversation data)
   */
  onTriggerCheckpointSave?: () => void;
}

// ============================================
// Tool Grouping Utilities
// ============================================

/**
 * Tool category types
 */
type ToolCategory = "write" | "read" | "edit" | "delete" | "command" | "install" | "preview" | "worker" | "other";

/**
 * Get tool category from tool name
 */
function getToolCategory(name: string): ToolCategory {
  const toolName = name.toLowerCase();

  if (toolName.includes("write_file") || toolName.includes("create_file")) return "write";
  if (toolName.includes("read_file")) return "read";
  if (toolName.includes("edit_file")) return "edit";
  if (toolName.includes("delete_file")) return "delete";
  if (toolName.includes("run_command") || toolName.includes("execute") || toolName.includes("shell")) return "command";
  if (toolName.includes("install")) return "install";
  if (toolName.includes("screenshot") || toolName.includes("preview") || toolName.includes("dom") || toolName.includes("console")) return "preview";
  if (toolName.includes("spawn") || toolName.includes("worker")) return "worker";

  return "other";
}

/**
 * Get file path from tool input
 */
function getFilePath(input: Record<string, unknown>): string {
  return (input.path as string) || (input.file_path as string) || "";
}

/**
 * Get file name from path
 */
function getFileName(path: string): string {
  return path.split("/").pop() || path;
}

/**
 * Category display info with Lucide icons
 */
const CATEGORY_INFO: Record<ToolCategory, {
  Icon: React.ComponentType<{ className?: string }>;
  label: string;
  verb: string
}> = {
  write: { Icon: FileText, label: "Writing", verb: "Wrote" },
  read: { Icon: Search, label: "Reading", verb: "Read" },
  edit: { Icon: Pencil, label: "Editing", verb: "Edited" },
  delete: { Icon: Trash2, label: "Deleting", verb: "Deleted" },
  command: { Icon: Play, label: "Running", verb: "Executed" },
  install: { Icon: Package, label: "Installing", verb: "Installed" },
  preview: { Icon: Eye, label: "Inspecting", verb: "Inspected" },
  worker: { Icon: Settings2, label: "Spawning", verb: "Spawned" },
  other: { Icon: Settings2, label: "Executing", verb: "Executed" },
};

/**
 * Grouped tool call item
 */
interface GroupedToolItem {
  toolCall: ToolCall;
  displayName: string;
}

/**
 * Tool group
 */
interface ToolGroup {
  category: ToolCategory;
  items: GroupedToolItem[];
  isComplete: boolean;
  hasError: boolean;
}

/**
 * Group consecutive tool calls by category
 */
function groupToolCalls(toolCalls: ToolCall[]): ToolGroup[] {
  if (toolCalls.length === 0) return [];

  const groups: ToolGroup[] = [];
  let currentGroup: ToolGroup | null = null;

  for (const toolCall of toolCalls) {
    const category = getToolCategory(toolCall.name);
    const input = toolCall.input || {};

    // Determine display name based on category
    let displayName: string;
    if (category === "write" || category === "read" || category === "edit" || category === "delete") {
      displayName = getFileName(getFilePath(input));
    } else if (category === "command") {
      const cmd = (input.command as string) || (input.raw_command as string) || "";
      displayName = cmd.length > 40 ? cmd.slice(0, 40) + "..." : cmd;
    } else if (category === "install") {
      displayName = "dependencies";
    } else if (category === "worker") {
      const sections = input.sections as Array<{ section_name: string }> | undefined;
      displayName = sections ? `${sections.length} workers` : "workers";
    } else {
      displayName = toolCall.name.replace(/_/g, " ");
    }

    // Check if we should start a new group
    if (!currentGroup || currentGroup.category !== category) {
      currentGroup = {
        category,
        items: [],
        isComplete: true,
        hasError: false,
      };
      groups.push(currentGroup);
    }

    // Add to current group
    currentGroup.items.push({ toolCall, displayName });

    // Update group status
    if (toolCall.status === "pending" || toolCall.status === "executing") {
      currentGroup.isComplete = false;
    }
    if (toolCall.status === "error") {
      currentGroup.hasError = true;
    }
  }

  return groups;
}

/**
 * Processed content block types
 */
type ProcessedBlock =
  | { type: "text"; content: string }
  | { type: "tool_group"; group: ToolGroup }
  | { type: "tool_call"; toolCall: ToolCall }; // For special cases like worker spawn

/**
 * Process content blocks to group consecutive tool calls
 */
function processContentBlocks(blocks: ContentBlock[]): ProcessedBlock[] {
  const result: ProcessedBlock[] = [];
  let consecutiveToolCalls: ToolCall[] = [];

  const flushToolCalls = () => {
    if (consecutiveToolCalls.length === 0) return;

    const groups = groupToolCalls(consecutiveToolCalls);
    for (const group of groups) {
      // Special handling for worker spawn - keep as individual
      if (group.category === "worker") {
        for (const item of group.items) {
          result.push({ type: "tool_call", toolCall: item.toolCall });
        }
      } else {
        result.push({ type: "tool_group", group });
      }
    }
    consecutiveToolCalls = [];
  };

  for (const block of blocks) {
    if (block.type === "text") {
      flushToolCalls();
      // Only add non-empty text blocks
      if (block.content && block.content.trim()) {
        result.push({ type: "text", content: block.content });
      }
    } else if (block.type === "tool_call") {
      consecutiveToolCalls.push(block.toolCall);
    }
  }

  flushToolCalls();
  return result;
}

// ============================================
// Grouped Tool Calls Component
// ============================================

/**
 * Single item in grouped tool calls - minimal style
 */
function GroupedToolItem({ item, isLast, showConnector = true }: {
  item: GroupedToolItem;
  isLast: boolean;
  showConnector?: boolean;
}) {
  const [isDetailExpanded, setIsDetailExpanded] = useState(false);
  const itemRunning = item.toolCall.status === "pending" || item.toolCall.status === "executing";
  const itemSuccess = item.toolCall.status === "success";
  const itemError = item.toolCall.status === "error";

  return (
    <div>
      {/* Item row */}
      <button
        onClick={() => setIsDetailExpanded(!isDetailExpanded)}
        className="flex items-center gap-1.5 py-0.5 w-full text-left hover:opacity-80 transition-opacity"
      >
        {/* Expand indicator */}
        <span className="text-neutral-500 flex-shrink-0">
          {isDetailExpanded ? (
            <ChevronDown className="h-2.5 w-2.5" />
          ) : (
            <ChevronRight className="h-2.5 w-2.5" />
          )}
        </span>

        {/* File name */}
        <span className={cn(
          "flex-1 truncate text-[11px] text-neutral-500 dark:text-neutral-400",
          itemError && "text-red-500 dark:text-red-400"
        )}>
          {item.displayName}
        </span>

        {/* Item status */}
        {itemRunning ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin text-neutral-400 flex-shrink-0" />
        ) : itemSuccess ? (
          <Check className="h-2.5 w-2.5 text-green-500 flex-shrink-0" />
        ) : itemError ? (
          <X className="h-2.5 w-2.5 text-red-500 flex-shrink-0" />
        ) : null}
      </button>

      {/* Expanded detail */}
      {isDetailExpanded && (
        <div className="ml-4 mt-1 mb-1.5 py-1.5 px-2 rounded bg-white dark:bg-black space-y-1.5">
          {/* Input */}
          {item.toolCall.input && Object.keys(item.toolCall.input).length > 0 && (
            <div>
              <span className="text-[9px] uppercase tracking-wide text-neutral-400 font-medium">
                Input
              </span>
              <pre className="mt-0.5 p-1.5 rounded text-[10px] leading-relaxed overflow-x-auto max-h-24 border border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 scrollbar-thin">
                {JSON.stringify(item.toolCall.input, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {item.toolCall.result && (
            <div>
              <span className="text-[9px] uppercase tracking-wide text-neutral-400 font-medium">
                Result
              </span>
              <pre className={cn(
                "mt-0.5 p-1.5 rounded text-[10px] leading-relaxed overflow-x-auto max-h-32 scrollbar-thin",
                "border border-dashed border-neutral-300 dark:border-neutral-700",
                item.toolCall.status === "error"
                  ? "text-red-500"
                  : "text-neutral-600 dark:text-neutral-400"
              )}>
                {item.toolCall.result}
              </pre>
            </div>
          )}

          {/* Error */}
          {item.toolCall.error && (
            <div className="flex items-start gap-1 p-1.5 rounded border border-dashed border-red-300 dark:border-red-800">
              <AlertCircle className="h-2.5 w-2.5 text-red-500 flex-shrink-0 mt-0.5" />
              <span className="text-[10px] text-red-600 dark:text-red-400">
                {item.toolCall.error}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Display a group of tool calls - minimal inline style
 */
function GroupedToolCallsDisplay({ group, workers }: { group: ToolGroup; workers?: WorkerState[] }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const info = CATEGORY_INFO[group.category];
  const itemCount = group.items.length;
  const Icon = info.Icon;

  // Determine overall status
  const isRunning = !group.isComplete;
  const isSuccess = group.isComplete && !group.hasError;
  const isError = group.hasError;

  return (
    <div className="text-left my-1">
      {/* Minimal inline display */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-left hover:opacity-80 transition-opacity"
      >
        {/* Icon */}
        <Icon className="h-3 w-3 text-neutral-400 dark:text-neutral-500 flex-shrink-0" />

        {/* Label */}
        <span className="text-xs text-neutral-500 dark:text-neutral-400">
          {isRunning ? info.label : info.verb} {itemCount} {itemCount === 1 ? "file" : "files"}
        </span>

        {/* Status indicator */}
        {isRunning ? (
          <Loader2 className="h-3 w-3 animate-spin text-neutral-400 flex-shrink-0" />
        ) : isSuccess ? (
          <Check className="h-3 w-3 text-green-500 flex-shrink-0" />
        ) : isError ? (
          <X className="h-3 w-3 text-red-500 flex-shrink-0" />
        ) : null}

        {/* Expand/collapse */}
        <span className="text-neutral-500">
          {isExpanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      </button>

      {/* Expanded file list */}
      {isExpanded && (
        <div className="mt-1.5 ml-4 space-y-0.5">
          {group.items.map((item, index) => (
            <GroupedToolItem
              key={item.toolCall.id}
              item={item}
              isLast={index === group.items.length - 1}
              showConnector={false}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// Tool Call Display Component
// ============================================

/**
 * Get human-readable action description based on tool name and input
 * 根据工具名称和输入获取人类可读的操作描述
 */
function getToolActionDescription(name: string, input: Record<string, unknown>): string {
  const toolName = name.toLowerCase();

  // File operations
  if (toolName.includes("write_file") || toolName.includes("create_file")) {
    const path = input.path as string || input.file_path as string || "";
    return `Writing ${path.split("/").pop() || "file"}`;
  }
  if (toolName.includes("read_file")) {
    const path = input.path as string || input.file_path as string || "";
    return `Reading ${path.split("/").pop() || "file"}`;
  }
  if (toolName.includes("edit_file")) {
    const path = input.path as string || input.file_path as string || "";
    return `Editing ${path.split("/").pop() || "file"}`;
  }
  if (toolName.includes("delete_file")) {
    const path = input.path as string || input.file_path as string || "";
    return `Deleting ${path.split("/").pop() || "file"}`;
  }
  if (toolName.includes("list_files") || toolName.includes("list_directory")) {
    return "Listing files";
  }

  // Terminal operations
  if (toolName.includes("run_command") || toolName.includes("execute")) {
    const cmd = input.command as string || "";
    const shortCmd = cmd.length > 30 ? cmd.slice(0, 30) + "..." : cmd;
    return `Running: ${shortCmd || "command"}`;
  }
  if (toolName.includes("install")) {
    return "Installing dependencies";
  }
  if (toolName.includes("start_server") || toolName.includes("dev_server")) {
    return "Starting dev server";
  }

  // Preview operations
  if (toolName.includes("screenshot")) {
    return "Taking screenshot";
  }
  if (toolName.includes("preview") || toolName.includes("dom")) {
    return "Checking preview";
  }
  if (toolName.includes("console")) {
    return "Reading console";
  }

  // Data operations
  if (toolName.includes("query") || toolName.includes("source")) {
    return "Querying data";
  }

  // Multi-Agent operations
  if (toolName.includes("spawn") || toolName.includes("worker")) {
    const sections = input.sections as Array<{ section_name: string }> | undefined;
    if (sections && sections.length > 0) {
      return `Spawning ${sections.length} Worker Agents`;
    }
    return "Spawning Worker Agents";
  }
  if (toolName.includes("section_data")) {
    return "Get Section Data";
  }

  // Default: humanize the tool name
  return name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function ToolCallDisplay({ toolCall, workers }: { toolCall: ToolCall; workers?: WorkerState[] }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const actionDescription = getToolActionDescription(toolCall.name, toolCall.input || {});

  const isRunning = toolCall.status === "pending" || toolCall.status === "executing";
  const isSuccess = toolCall.status === "success";
  const isError = toolCall.status === "error";

  // Check if this is a spawn_section_workers call
  const isSpawnWorkers = toolCall.name.toLowerCase().includes("spawn") &&
    toolCall.name.toLowerCase().includes("worker");

  // Calculate elapsed time for running tools
  useEffect(() => {
    if (isRunning && toolCall.startTime) {
      const interval = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - toolCall.startTime!) / 1000));
      }, 100);
      return () => clearInterval(interval);
    } else if (!isRunning && toolCall.startTime && toolCall.endTime) {
      setElapsedTime(Math.floor((toolCall.endTime - toolCall.startTime) / 1000));
    }
  }, [isRunning, toolCall.startTime, toolCall.endTime]);

  // Format time display
  const timeDisplay = toolCall.startTime ? `${elapsedTime}s` : null;

  return (
    <div className="text-left my-1">
      {/* Minimal inline display */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-left hover:opacity-80 transition-opacity"
      >
        {/* Status Indicator */}
        {isRunning ? (
          <Loader2 className="h-3 w-3 animate-spin text-neutral-400 flex-shrink-0" />
        ) : isSuccess ? (
          <Check className="h-3 w-3 text-green-500 flex-shrink-0" />
        ) : isError ? (
          <X className="h-3 w-3 text-red-500 flex-shrink-0" />
        ) : (
          <Settings2 className="h-3 w-3 text-neutral-400 dark:text-neutral-500 flex-shrink-0" />
        )}

        {/* Action Description */}
        <span className="text-xs text-neutral-500 dark:text-neutral-400">
          {actionDescription}
        </span>

        {/* Time Display */}
        {timeDisplay && (
          <span className="text-[10px] text-neutral-400 dark:text-neutral-500 tabular-nums">
            {timeDisplay}
          </span>
        )}

        {/* Expand/Collapse */}
        <span className="text-neutral-400">
          {isExpanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      </button>

      {/* Worker Agents Display */}
      {isSpawnWorkers && workers && workers.length > 0 && (
        <div className="mt-1.5 ml-4">
          <WorkerDisplay workers={workers} />
        </div>
      )}

      {/* Expanded Content */}
      {isExpanded && (
        <div className="mt-1.5 ml-4 space-y-1.5 py-1.5 px-2 rounded bg-white dark:bg-black">
          {/* Input */}
          <div>
            <span className="text-[9px] uppercase tracking-wide text-neutral-400 font-medium">
              Input
            </span>
            <pre className="mt-0.5 p-1.5 rounded text-[10px] leading-relaxed overflow-x-auto max-h-24 border border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 scrollbar-thin">
              {JSON.stringify(toolCall.input, null, 2)}
            </pre>
          </div>

          {/* Result */}
          {toolCall.result && (
            <div>
              <span className="text-[9px] uppercase tracking-wide text-neutral-400 font-medium">
                Result
              </span>
              <pre className={cn(
                "mt-0.5 p-1.5 rounded text-[10px] leading-relaxed overflow-x-auto max-h-32 scrollbar-thin",
                "border border-dashed border-neutral-300 dark:border-neutral-700",
                toolCall.status === "error"
                  ? "text-red-500"
                  : "text-neutral-600 dark:text-neutral-400"
              )}>
                {toolCall.result}
              </pre>
            </div>
          )}

          {/* Error */}
          {toolCall.error && (
            <div className="flex items-start gap-1 p-1.5 rounded border border-dashed border-red-300 dark:border-red-800">
              <AlertCircle className="h-2.5 w-2.5 text-red-500 flex-shrink-0 mt-0.5" />
              <span className="text-[10px] text-red-600 dark:text-red-400">
                {toolCall.error}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================
// Worker Display Component (Multi-Agent)
// ============================================

function WorkerDisplay({ workers }: { workers: WorkerState[] }) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (workers.length === 0) return null;

  const activeWorkers = workers.filter(w => w.status === "started" || w.status === "running");
  const allComplete = workers.every(w => w.status === "completed" || w.status === "error");
  const hasError = workers.some(w => w.status === "error");

  return (
    <div className="my-1">
      {/* Minimal inline header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-left hover:opacity-80 transition-opacity"
      >
        <Settings2 className="h-3 w-3 text-neutral-400 dark:text-neutral-500 flex-shrink-0" />
        <span className="text-xs text-neutral-500 dark:text-neutral-400">
          Spawned {workers.length} worker{workers.length > 1 ? "s" : ""}
          {activeWorkers.length > 0 && ` (${activeWorkers.length} running)`}
        </span>

        {/* Status indicator */}
        {!allComplete ? (
          <Loader2 className="h-3 w-3 animate-spin text-neutral-400 flex-shrink-0" />
        ) : hasError ? (
          <X className="h-3 w-3 text-red-500 flex-shrink-0" />
        ) : (
          <Check className="h-3 w-3 text-green-500 flex-shrink-0" />
        )}

        <span className="text-neutral-500">
          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      </button>

      {/* Worker List */}
      {isExpanded && (
        <div className="mt-1 ml-4 space-y-0.5">
          {workers.map((worker, index) => (
            <WorkerItem
              key={worker.worker_id}
              worker={worker}
              isLast={index === workers.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Single tool item with expandable details - minimal style
function WorkerToolItem({ tool, index }: { tool: WorkerToolHistory; index: number }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const hasCode = tool.result && (
    tool.result.includes("```") ||
    tool.tool_name.includes("write_code") ||
    tool.tool_name.includes("query_section_data")
  );

  return (
    <div>
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1 w-full text-left hover:opacity-80 py-0.5 transition-opacity"
      >
        <span className="text-neutral-500 flex-shrink-0">
          {isExpanded ? <ChevronDown className="h-2 w-2" /> : <ChevronRight className="h-2 w-2" />}
        </span>
        <span className="text-neutral-500 dark:text-neutral-400 text-[10px] truncate flex-1">
          {tool.tool_name}
        </span>
        {tool.status === "executing" ? (
          <Loader2 className="h-2 w-2 animate-spin text-neutral-400 flex-shrink-0" />
        ) : tool.status === "success" ? (
          <Check className="h-2 w-2 text-green-500 flex-shrink-0" />
        ) : (
          <X className="h-2 w-2 text-red-500 flex-shrink-0" />
        )}
      </button>

      {/* Expanded details */}
      {isExpanded && (
        <div className="ml-3 mt-0.5 mb-1 space-y-1 py-1 px-1.5 rounded bg-white dark:bg-black">
          {/* Input */}
          {tool.input && Object.keys(tool.input).length > 0 && (
            <div>
              <span className="text-[8px] uppercase tracking-wide text-neutral-400 font-medium">
                Input
              </span>
              <pre className="mt-0.5 p-1 rounded text-[9px] leading-relaxed overflow-x-auto max-h-20 border border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 scrollbar-thin">
                {JSON.stringify(tool.input, null, 2)}
              </pre>
            </div>
          )}

          {/* Result */}
          {tool.result && (
            <div>
              <span className="text-[8px] uppercase tracking-wide text-neutral-400 font-medium">
                Result
              </span>
              <pre className={cn(
                "mt-0.5 p-1 rounded text-[9px] leading-relaxed overflow-x-auto scrollbar-thin",
                hasCode ? "max-h-40" : "max-h-20",
                "border border-dashed border-neutral-300 dark:border-neutral-700",
                tool.status === "error"
                  ? "text-red-500"
                  : "text-neutral-600 dark:text-neutral-400"
              )}>
                {tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function WorkerItem({ worker, isLast = false }: { worker: WorkerState; isLast?: boolean }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const statusIcon = {
    spawned: <Loader2 className="h-2.5 w-2.5 text-neutral-400" />,
    started: <Loader2 className="h-2.5 w-2.5 animate-spin text-neutral-400" />,
    running: <Loader2 className="h-2.5 w-2.5 animate-spin text-neutral-400" />,
    completed: <Check className="h-2.5 w-2.5 text-green-500" />,
    error: <X className="h-2.5 w-2.5 text-red-500" />,
  };

  return (
    <div>
      {/* Item row */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 py-0.5 w-full text-left hover:opacity-80 transition-opacity"
      >
        {/* Expand indicator */}
        <span className="text-neutral-500 flex-shrink-0">
          {isExpanded ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
        </span>

        {/* Worker name */}
        <span className="flex-1 truncate text-[11px] text-neutral-500 dark:text-neutral-400">
          {worker.display_name || worker.section_name}
        </span>

        {/* Show current tool if running */}
        {worker.current_tool && (
          <span className="text-[10px] text-neutral-400 truncate max-w-24">
            {worker.current_tool}
          </span>
        )}

        {/* Status */}
        {statusIcon[worker.status]}
      </button>

      {isExpanded && (
        <div className="ml-4 mt-1 mb-1.5 py-1.5 px-2 rounded bg-white dark:bg-black space-y-1.5">
          {/* Task description */}
          {worker.task_description && (
            <p className="text-[10px] text-neutral-500 dark:text-neutral-400 leading-relaxed">
              {worker.task_description}
            </p>
          )}

          {/* Reasoning text from worker */}
          {worker.reasoning_text && (
            <div>
              <span className="text-[9px] uppercase tracking-wide text-neutral-400 font-medium">
                Reasoning
              </span>
              <div className="mt-0.5 p-1.5 rounded border border-dashed border-neutral-300 dark:border-neutral-700 text-[10px] text-neutral-600 dark:text-neutral-400 leading-relaxed max-h-24 overflow-y-auto whitespace-pre-wrap scrollbar-thin">
                {worker.reasoning_text}
              </div>
            </div>
          )}

          {/* Tool history */}
          {worker.tool_history.length > 0 && (
            <div className="space-y-0.5">
              {worker.tool_history.map((tool, i) => (
                <WorkerToolItem key={i} tool={tool} index={i} />
              ))}
            </div>
          )}

          {/* Summary or error */}
          {worker.summary && (
            <p className="text-[10px] text-green-600 dark:text-green-400 flex items-center gap-1">
              <Check className="h-2.5 w-2.5" />
              {worker.summary}
            </p>
          )}
          {worker.error && (
            <p className="text-[10px] text-red-600 dark:text-red-400 flex items-center gap-1">
              <X className="h-2.5 w-2.5" />
              {worker.error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================
// Message Component
// ============================================

function MessageItem({ message, workers }: { message: ChatMessage; workers?: WorkerState[] }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // System messages have special styling
  if (isSystem) {
    return (
      <div className="flex justify-center my-3">
        <div className="max-w-[85%] px-4 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-700 overflow-hidden">
          <div className="text-xs text-emerald-700 dark:text-emerald-400 whitespace-pre-line break-all">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // User messages - bubble on right
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] flex flex-col items-end gap-1.5">
          {/* Display attached images */}
          {message.images && message.images.length > 0 && (
            <div className="flex gap-1.5 flex-wrap justify-end">
              {message.images.map((img, idx) => (
                <div
                  key={idx}
                  className="w-20 h-20 rounded-lg overflow-hidden border border-neutral-300 dark:border-neutral-600"
                >
                  <img
                    src={img}
                    alt={`Attached ${idx + 1}`}
                    className="w-full h-full object-cover"
                  />
                </div>
              ))}
            </div>
          )}
          {/* Message text */}
          {message.content && (
            <div className="px-3 py-2 rounded-2xl rounded-tr-md bg-neutral-200 dark:bg-neutral-800 text-neutral-900 dark:text-white overflow-hidden">
              <p className="text-xs leading-relaxed whitespace-pre-wrap break-all">{message.content}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // AI messages - minimal style, pure white text
  // Check if message is empty (thinking state)
  const hasContent = message.content || (message.contentBlocks && message.contentBlocks.length > 0);
  const isThinking = message.isThinking && !hasContent;

  return (
    <div className="flex">
      {/* Content - plain text */}
      <div className="flex-1 max-w-full space-y-1.5 overflow-hidden">
        {/* Thinking indicator - shown when AI is processing but no content yet */}
        {isThinking && (
          <div className="flex items-center gap-2 py-1">
            <Loader2 className="h-3 w-3 animate-spin text-neutral-400" />
            <span className="text-xs text-neutral-500 dark:text-neutral-400">Thinking...</span>
          </div>
        )}
        {/* Text content or content blocks - with tool call grouping */}
        {message.contentBlocks ? (
          // Process and group consecutive tool calls
          processContentBlocks(message.contentBlocks).map((block, i) => (
            <div key={i}>
              {block.type === "text" && block.content && (
                <p className="text-xs leading-relaxed text-neutral-800 dark:text-white whitespace-pre-wrap break-words">
                  {block.content}
                </p>
              )}
              {block.type === "tool_group" && (
                <GroupedToolCallsDisplay group={block.group} workers={workers} />
              )}
              {block.type === "tool_call" && (
                <ToolCallDisplay toolCall={block.toolCall} workers={workers} />
              )}
            </div>
          ))
        ) : (
          <p className="text-xs leading-relaxed text-neutral-800 dark:text-white whitespace-pre-wrap break-words">
            {message.content}
          </p>
        )}

        {/* Standalone tool calls (if not in content blocks) - also group them */}
        {!message.contentBlocks && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-1 mt-1.5">
            {groupToolCalls(message.toolCalls).map((group, i) => (
              group.category === "worker" ? (
                // Worker spawns shown individually
                group.items.map((item) => (
                  <ToolCallDisplay key={item.toolCall.id} toolCall={item.toolCall} workers={workers} />
                ))
              ) : (
                <GroupedToolCallsDisplay key={i} group={group} workers={workers} />
              )
            ))}
          </div>
        )}

      </div>
    </div>
  );
}

// ============================================
// Chat Input Component
// ============================================

// Attached image type
interface AttachedImage {
  id: string;
  file: File;
  preview: string; // base64 data URL for preview
}

function ChatInput({
  onSend,
  isLoading,
}: {
  onSend: (message: string, images?: string[]) => void;
  isLoading: boolean;
}) {
  const [input, setInput] = useState("");
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  // Fixed height - no auto-resize (keep 2 lines height)
  const adjustHeight = useCallback(() => {
    // Do nothing - keep fixed height
  }, []);

  // Adjust height when input changes
  useEffect(() => {
    adjustHeight();
  }, [input, adjustHeight]);

  // Process files (filter for images and convert to base64)
  const processFiles = useCallback(async (files: FileList | File[]) => {
    const imageFiles = Array.from(files).filter(file =>
      file.type.startsWith('image/')
    );

    // Limit to 4 images max
    const remainingSlots = 4 - images.length;
    const filesToProcess = imageFiles.slice(0, remainingSlots);

    const newImages: AttachedImage[] = await Promise.all(
      filesToProcess.map(async (file) => {
        const preview = await new Promise<string>((resolve) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result as string);
          reader.readAsDataURL(file);
        });
        return {
          id: `img-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          file,
          preview,
        };
      })
    );

    setImages(prev => [...prev, ...newImages]);
  }, [images.length]);

  // Handle file input change
  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
      // Reset input so same file can be selected again
      e.target.value = '';
    }
  }, [processFiles]);

  // Remove an image
  const removeImage = useCallback((id: string) => {
    setImages(prev => prev.filter(img => img.id !== id));
  }, []);

  // Drag and drop handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only set dragging to false if we're leaving the drop zone entirely
    if (dropZoneRef.current && !dropZoneRef.current.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      processFiles(files);
    }
  }, [processFiles]);

  // Handle paste event for images
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    const imageFiles: File[] = [];

    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) {
          imageFiles.push(file);
        }
      }
    }

    if (imageFiles.length > 0) {
      processFiles(imageFiles);
    }
  }, [processFiles]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if ((!input.trim() && images.length === 0) || isLoading) return;

    // Convert images to base64 strings for sending
    const imageBase64s = images.map(img => img.preview);
    onSend(input.trim(), imageBase64s.length > 0 ? imageBase64s : undefined);

    setInput("");
    setImages([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const canSubmit = (input.trim() || images.length > 0) && !isLoading;

  return (
    <form onSubmit={handleSubmit}>
      {/* Drop zone wrapper - entire input area (fixed height) */}
      <div
        ref={dropZoneRef}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={cn(
          "relative flex flex-col",
          "bg-neutral-100 dark:bg-neutral-900",
          "border border-neutral-300 dark:border-neutral-700",
          "rounded-xl",
          "focus-within:border-neutral-400 dark:focus-within:border-neutral-600",
          isDragging && "border-blue-500 dark:border-blue-400",
          // Fixed height when no images attached
          images.length === 0 && "h-[92px]"
        )}
      >
        {/* Drag overlay */}
        {isDragging && (
          <div className={cn(
            "absolute inset-0 z-10 rounded-xl",
            "bg-blue-500/10 dark:bg-blue-400/10",
            "border-2 border-dashed border-blue-500 dark:border-blue-400",
            "flex items-center justify-center pointer-events-none"
          )}>
            <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400">
              <ImageIcon className="h-5 w-5" />
              <span className="text-sm font-medium">Drop images here</span>
            </div>
          </div>
        )}

        {/* Image previews */}
        {images.length > 0 && (
          <div className="flex gap-2 px-3 pt-2 flex-wrap">
            {images.map((img) => (
              <div
                key={img.id}
                className="relative group w-14 h-14 rounded-lg overflow-hidden border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800"
              >
                <img
                  src={img.preview}
                  alt="Attached"
                  className="w-full h-full object-cover"
                />
                <button
                  type="button"
                  onClick={() => removeImage(img.id)}
                  className={cn(
                    "absolute top-0.5 right-0.5 p-0.5 rounded-full",
                    "bg-black/60 text-white",
                    "opacity-0 group-hover:opacity-100 transition-opacity"
                  )}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Text area - expands upward */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask a follow-up..."
          disabled={isLoading}
          className={cn(
            "w-full h-[52px] px-3 py-2",
            "bg-transparent",
            "text-sm resize-none overflow-y-auto",
            "text-neutral-900 dark:text-white",
            "placeholder-neutral-500 dark:placeholder-neutral-500",
            "focus:outline-none",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          rows={2}
        />

        {/* Bottom toolbar - fixed at bottom */}
        <div className="flex items-center justify-between px-2 pb-2">
          {/* Plus button (left side) */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || images.length >= 4}
            className={cn(
              "p-1.5 rounded-md transition-all",
              "text-neutral-500 dark:text-neutral-400",
              "hover:text-neutral-700 dark:hover:text-neutral-200",
              "hover:bg-neutral-200 dark:hover:bg-neutral-800",
              "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            )}
            title={images.length >= 4 ? "Maximum 4 images" : "Attach images"}
          >
            <Plus className="h-4 w-4" strokeWidth={2} />
          </button>

          {/* Submit button (right side) */}
          <button
            type="submit"
            disabled={!canSubmit}
            className={cn(
              "p-1.5 rounded-md transition-all",
              canSubmit
                ? "bg-neutral-900 dark:bg-white text-white dark:text-black hover:bg-neutral-700 dark:hover:bg-neutral-200"
                : "border border-neutral-400 dark:border-neutral-600 text-neutral-400 dark:text-neutral-500 bg-transparent"
            )}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" strokeWidth={2} />
            )}
          </button>
        </div>

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          onChange={handleFileChange}
          className="hidden"
        />
      </div>
    </form>
  );
}

// ============================================
// Main Chat Panel Component
// ============================================

// Connection state for WebSocket
type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

export function NextingAgentChatPanel({
  onWebContainerAction,
  getWebContainerState,
  messages,
  onMessagesChange,
  selectedSource,
  onClearSource,
  onLoadingChange,
  onClearFileDiffs,
  className,
  mode = "webcontainer",
  sandboxId,
  boxliteState,
  onBoxLiteStateUpdate,
  onProjectNameGenerated,
  autoSendMessage = "Copy this web for me",
  shouldAutoSend = false,
  onAutoSendComplete,
  onTriggerCheckpointSave,
}: NextingAgentChatPanelProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number>(0);
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  // Worker Agent state (Multi-Agent)
  const [workers, setWorkers] = useState<WorkerState[]>([]);
  // Source indicator collapsed state - auto-collapse when agent starts
  const [isSourceCollapsed, setIsSourceCollapsed] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Scroll container ref for smart auto-scroll
  // 滚动容器引用，用于智能自动滚动
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // Track if user is at bottom of scroll
  // 跟踪用户是否在滚动条底部
  const isAtBottomRef = useRef(true);

  // WebSocket client reference (supports both WebContainer and BoxLite modes)
  const clientRef = useRef<NextingAgentClient | BoxLiteAgentClient | null>(null);

  // Track if project naming has been triggered (only trigger once)
  const namingTriggeredRef = useRef(false);

  // Refs for BoxLite mode
  const boxliteStateRef = useRef(boxliteState);
  const onBoxLiteStateUpdateRef = useRef(onBoxLiteStateUpdate);
  const onTriggerCheckpointSaveRef = useRef(onTriggerCheckpointSave);
  useEffect(() => {
    boxliteStateRef.current = boxliteState;
  }, [boxliteState]);
  useEffect(() => {
    onBoxLiteStateUpdateRef.current = onBoxLiteStateUpdate;
  }, [onBoxLiteStateUpdate]);
  useEffect(() => {
    onTriggerCheckpointSaveRef.current = onTriggerCheckpointSave;
  }, [onTriggerCheckpointSave]);

  // Content blocks builder for streaming response
  const blocksBuilderRef = useRef<ContentBlock[]>([]);

  // Current assistant message being built
  const currentMessageRef = useRef<ChatMessage | null>(null);

  // Track messages for WebSocket callbacks (they can't access latest state)
  const messagesRef = useRef<ChatMessage[]>(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Generate unique ID
  const generateId = useCallback(
    () => `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    []
  );

  // Update elapsed time counter
  useEffect(() => {
    if (!isLoading || !startTime) {
      setElapsedTime(0);
      return;
    }

    const interval = setInterval(() => {
      setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    return () => clearInterval(interval);
  }, [isLoading, startTime]);

  // Notify parent when loading state changes (for disabling source selection)
  useEffect(() => {
    onLoadingChange?.(isLoading);
  }, [isLoading, onLoadingChange]);

  // Auto-collapse source indicator when agent starts running
  // 当 Agent 开始运行时自动折叠 source indicator
  useEffect(() => {
    if (isLoading) {
      setIsSourceCollapsed(true);
    }
  }, [isLoading]);

  // Handle scroll event to detect if user is at bottom
  // 处理滚动事件，检测用户是否在底部
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Calculate if user is at bottom (with 50px threshold for tolerance)
    // 计算用户是否在底部（50px容差）
    const { scrollTop, scrollHeight, clientHeight } = container;
    const threshold = 50;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < threshold;
    isAtBottomRef.current = isAtBottom;
  }, []);

  // Smart auto-scroll: only scroll to bottom if user is already at bottom
  // 智能自动滚动：只有当用户已经在底部时才滚动
  useEffect(() => {
    if (isAtBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  // Refs for callbacks (to avoid re-creating WebSocket on callback changes)
  const onWebContainerActionRef = useRef(onWebContainerAction);
  const onMessagesChangeRef = useRef(onMessagesChange);
  const getWebContainerStateRef = useRef(getWebContainerState);

  // Keep refs updated
  useEffect(() => {
    onWebContainerActionRef.current = onWebContainerAction;
  }, [onWebContainerAction]);

  useEffect(() => {
    onMessagesChangeRef.current = onMessagesChange;
  }, [onMessagesChange]);

  useEffect(() => {
    getWebContainerStateRef.current = getWebContainerState;
  }, [getWebContainerState]);

  // Handle execute_action requests from backend (using ref)
  const handleExecuteAction = useCallback(
    async (request: ExecuteActionRequest): Promise<{ success: boolean; result: string; error?: string }> => {
      console.log("[ChatPanel] handleExecuteAction called:", {
        action_type: request.action_type,
        action_id: request.action_id,
        payload: request.payload,
      });

      const actionHandler = onWebContainerActionRef.current;
      if (!actionHandler) {
        console.error("[ChatPanel] No actionHandler available!");
        return { success: false, result: "", error: "WebContainer not available" };
      }

      try {
        // Map action_type to WebContainerAction format
        const action: WebContainerAction = {
          type: request.action_type as WebContainerAction["type"],
          payload: request.payload as WebContainerAction["payload"],
        };

        console.log("[ChatPanel] Calling actionHandler with:", action);
        const startTime = Date.now();
        const result = await actionHandler(action);
        const duration = Date.now() - startTime;
        console.log(`[ChatPanel] actionHandler completed in ${duration}ms, result length: ${result?.length || 0}`);

        // Use shared error detection function from use-webcontainer
        const isSuccess = !isActionError(result);

        return {
          success: isSuccess,
          result: result.slice(0, 2000), // Limit size
          error: isSuccess ? undefined : result,
        };
      } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        console.error("[ChatPanel] Action error:", errorMsg);
        return { success: false, result: "", error: errorMsg };
      }
    },
    [] // No dependencies - uses refs
  );

  // Initialize WebSocket connection
  useEffect(() => {
    // Get auth token
    const initConnection = async () => {
      // === BoxLite Mode: Connect to BoxLite Agent ===
      if (mode === "boxlite") {
        if (!sandboxId) {
          console.error("[Agent] sandboxId is required for boxlite mode");
          setConnectionState("error");
          return;
        }

        console.log("[Agent] Creating client for sandbox:", sandboxId);

        const boxliteClient = createBoxLiteAgentClient({
          sandboxId,
          onOpen: () => {
            console.log("[Agent] Connected");
            setConnectionState("connected");
          },
          onClose: () => {
            console.log("[Agent] Disconnected");
            setConnectionState("disconnected");
            setIsLoading(false);
          },
          onError: () => {
            console.warn("[Agent] Connection error - backend may not be running");
            setConnectionState("error");
            setIsLoading(false);
          },
          onText: (content: string) => {
            const blocksBuilder = blocksBuilderRef.current;
            const lastBlock = blocksBuilder[blocksBuilder.length - 1];
            if (lastBlock?.type === "text") {
              lastBlock.content = content;
            } else {
              blocksBuilder.push({ type: "text", content });
            }
            updateCurrentMessage();
          },
          onTextDelta: (delta: string) => {
            const blocksBuilder = blocksBuilderRef.current;
            const lastBlock = blocksBuilder[blocksBuilder.length - 1];
            if (lastBlock?.type === "text") {
              lastBlock.content += delta;
            } else {
              blocksBuilder.push({ type: "text", content: delta });
            }
            updateCurrentMessage();
          },
          onToolCall: (toolCall: { id: string; name: string; input: Record<string, unknown> }) => {
            const blocksBuilder = blocksBuilderRef.current;
            blocksBuilder.push({
              type: "tool_call",
              toolCall: {
                id: toolCall.id,
                name: toolCall.name,
                input: toolCall.input,
                status: "executing",
                startTime: Date.now(),
              },
            });
            setCurrentTool(toolCall.name);
            updateCurrentMessage();
          },
          onToolResult: (result: { id: string; success: boolean; result: string }) => {
            const blocksBuilder = blocksBuilderRef.current;
            for (const block of blocksBuilder) {
              if (block.type === "tool_call" && block.toolCall.id === result.id) {
                block.toolCall.status = result.success ? "success" : "error";
                block.toolCall.result = result.result;
                block.toolCall.endTime = Date.now();
                break;
              }
            }
            setCurrentTool(null);
            updateCurrentMessage();
          },
          onStateUpdate: (state: BoxLiteSandboxState) => {
            // Update BoxLite state when received from server
            onBoxLiteStateUpdateRef.current?.(state);
          },
          onDone: () => {
            const blocksBuilder = blocksBuilderRef.current;
            const currentMessage = currentMessageRef.current;
            const currentMessages = messagesRef.current;

            if (currentMessage) {
              const finalMessage: ChatMessage = {
                ...currentMessage,
                contentBlocks: [...blocksBuilder],
                content: blocksBuilder
                  .filter((b): b is ContentBlock & { type: "text" } => b.type === "text")
                  .map((b) => b.content)
                  .join(""),
                isThinking: false,
              };

              const updated = [...currentMessages];
              const idx = updated.findIndex((m) => m.id === currentMessage.id);
              if (idx >= 0) {
                updated[idx] = finalMessage;
              }
              messagesRef.current = updated;
              onMessagesChangeRef.current(updated);
            }

            blocksBuilderRef.current = [];
            currentMessageRef.current = null;
            setIsLoading(false);
            setCurrentTool(null);
          },
          // Checkpoint save trigger from backend
          onTriggerCheckpointSave: (payload) => {
            console.log("[Agent] Backend triggered checkpoint save, files:", payload.files_count);
            onTriggerCheckpointSaveRef.current?.();
          },
          // Worker events (for future BoxLite Worker support)
          onWorkerSpawned: (payload) => {
            setWorkers(prev => {
              const exists = prev.find(w => w.worker_id === payload.worker_id);
              if (exists) return prev;
              return [...prev, {
                worker_id: payload.worker_id,
                section_name: payload.section_name,
                display_name: payload.display_name,
                status: "spawned",
                task_description: payload.task_description,
                tool_history: [],
                files: [],
                input_data: payload.input_data ? {
                  html_lines: payload.input_data.html_lines,
                  html_chars: payload.input_data.html_chars,
                  html_range: payload.input_data.html_range,
                  char_start: payload.input_data.char_start,
                  char_end: payload.input_data.char_end,
                  estimated_tokens: payload.input_data.estimated_tokens,
                  images_count: payload.input_data.images_count,
                  links_count: payload.input_data.links_count,
                } : undefined,
              }];
            });
          },
          onWorkerStarted: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id ? { ...w, status: "started" as const } : w
            ));
          },
          onWorkerToolCall: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id
                ? {
                    ...w,
                    status: "running" as const,
                    current_tool: payload.tool_name,
                    tool_history: [...w.tool_history, {
                      tool_name: payload.tool_name,
                      status: "executing" as const,
                      input: payload.tool_input,
                    }],
                  }
                : w
            ));
          },
          onWorkerToolResult: (payload) => {
            setWorkers(prev => prev.map(w => {
              if (w.worker_id !== payload.worker_id) return w;
              const updatedHistory = [...w.tool_history];
              const lastTool = updatedHistory[updatedHistory.length - 1];
              if (lastTool && lastTool.tool_name === payload.tool_name) {
                lastTool.status = payload.success ? "success" : "error";
                lastTool.result = payload.result;
              }
              return { ...w, current_tool: undefined, tool_history: updatedHistory };
            }));
          },
          onWorkerCompleted: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id
                ? {
                    ...w,
                    status: payload.success ? "completed" as const : "error" as const,
                    files: payload.files,
                    summary: payload.summary,
                    error: payload.error,
                    current_tool: undefined,
                  }
                : w
            ));
          },
          onWorkerError: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id
                ? { ...w, status: "error" as const, error: payload.error, current_tool: undefined }
                : w
            ));
          },
          onWorkerIteration: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id
                ? { ...w, iteration: payload.iteration, max_iterations: payload.max_iterations }
                : w
            ));
          },
          onWorkerTextDelta: (payload) => {
            setWorkers(prev => prev.map(w =>
              w.worker_id === payload.worker_id
                ? { ...w, reasoning_text: (w.reasoning_text || "") + payload.text }
                : w
            ));
          },
        });

        clientRef.current = boxliteClient;

        setConnectionState("connecting");
        try {
          await boxliteClient.connect();
        } catch {
          setConnectionState("error");
        }
        return;
      }

      // === WebContainer Mode (default): Connect to Nexting Agent ===
      let token: string | undefined;
      try {
        const { createClient: createSupabaseClient } = await import("@/lib/supabase/client");
        const supabase = createSupabaseClient();
        const { data: { session } } = await supabase.auth.getSession();
        token = session?.access_token;
      } catch (e) {
        console.warn("[WebSocket] Failed to get auth token:", e);
      }

      // Create WebSocket client for WebContainer mode
      const client = createClient({
        token,
        onOpen: () => {
          console.log("[WebSocket] Connected");
          setConnectionState("connected");
        },
        onClose: () => {
          console.log("[WebSocket] Disconnected");
          setConnectionState("disconnected");
          setIsLoading(false);
        },
        onError: () => {
          // Use warn instead of error to avoid red console messages
          console.warn("[WebSocket] Connection error - backend may not be running");
          setConnectionState("error");
          setIsLoading(false);
        },
        onText: (content: string) => {
          // Full text received (non-streaming)
          const blocksBuilder = blocksBuilderRef.current;
          const lastBlock = blocksBuilder[blocksBuilder.length - 1];
          if (lastBlock?.type === "text") {
            lastBlock.content = content;
          } else {
            blocksBuilder.push({ type: "text", content });
          }
          updateCurrentMessage();
        },
        onTextDelta: (delta: string) => {
          // Streaming text delta
          const blocksBuilder = blocksBuilderRef.current;
          const lastBlock = blocksBuilder[blocksBuilder.length - 1];
          if (lastBlock?.type === "text") {
            lastBlock.content += delta;
          } else {
            blocksBuilder.push({ type: "text", content: delta });
          }
          updateCurrentMessage();
        },
        onToolCall: (toolCall: { id: string; name: string; input: Record<string, unknown> }) => {
          const blocksBuilder = blocksBuilderRef.current;
          blocksBuilder.push({
            type: "tool_call",
            toolCall: {
              id: toolCall.id,
              name: toolCall.name,
              input: toolCall.input,
              status: "executing",
              startTime: Date.now(),
            },
          });
          setCurrentTool(toolCall.name);
          updateCurrentMessage();
        },
        onToolResult: (result: { id: string; success: boolean; result: string }) => {
          const blocksBuilder = blocksBuilderRef.current;
          for (const block of blocksBuilder) {
            if (block.type === "tool_call" && block.toolCall.id === result.id) {
              block.toolCall.status = result.success ? "success" : "error";
              block.toolCall.result = result.result;
              block.toolCall.endTime = Date.now();
              break;
            }
          }
          setCurrentTool(null);
          updateCurrentMessage();
        },
        onExecuteAction: handleExecuteAction,
        // Worker Agent event handlers (Multi-Agent)
        onWorkerSpawned: (payload: WorkerSpawnedPayload) => {
          console.log("[Worker] Spawned:", payload);
          setWorkers(prev => {
            const exists = prev.find(w => w.worker_id === payload.worker_id);
            if (exists) return prev;
            return [...prev, {
              worker_id: payload.worker_id,
              section_name: payload.section_name,
              display_name: payload.display_name,  // Human-friendly name
              status: "spawned",
              task_description: payload.task_description,
              tool_history: [],
              files: [],
              // Store input data for UI display (html_lines, chars range, tokens, etc.)
              input_data: payload.input_data ? {
                html_lines: payload.input_data.html_lines,
                html_chars: payload.input_data.html_chars,
                html_range: payload.input_data.html_range,
                char_start: payload.input_data.char_start,
                char_end: payload.input_data.char_end,
                estimated_tokens: payload.input_data.estimated_tokens,
                images_count: payload.input_data.images_count,
                links_count: payload.input_data.links_count,
              } : undefined,
            }];
          });
        },
        onWorkerStarted: (payload: { worker_id: string; section_name: string }) => {
          console.log("[Worker] Started:", payload);
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? { ...w, status: "started" as const }
              : w
          ));
        },
        onWorkerToolCall: async (payload: WorkerToolCallPayload) => {
          console.log("[Worker] Tool call:", payload);

          // Update UI state
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? {
                  ...w,
                  status: "running" as const,
                  current_tool: payload.tool_name,
                  tool_history: [...w.tool_history, {
                    tool_name: payload.tool_name,
                    status: "executing" as const,
                    input: payload.tool_input,
                  }],
                }
              : w
          ));

          // Real-time file sync: write file to WebContainer immediately
          const actionHandler = onWebContainerActionRef.current;
          if (actionHandler) {
            const workerId = payload.worker_id;
            console.log(`[Worker:${workerId}] Starting file sync for tool: ${payload.tool_name}`);

            const syncOptions: FileSyncOptions = {
              onAction: actionHandler,
              onFileWritten: (path) => {
                console.log(`[Worker:${workerId}] ✓ File synced to WebContainer: ${path}`);
              },
              onError: (path, error) => {
                console.error(`[Worker:${workerId}] ✗ File sync failed: ${path}`, error);
              },
            };

            // Sync file write (non-blocking, fire and forget)
            syncWorkerFileWrite(
              payload.tool_name,
              payload.tool_input,
              syncOptions
            ).catch(err => {
              console.error(`[Worker:${workerId}] File sync error:`, err);
            });
          } else {
            console.warn(`[Worker:${payload.worker_id}] No actionHandler available for file sync!`);
          }
        },
        onWorkerToolResult: (payload: WorkerToolResultPayload) => {
          console.log("[Worker] Tool result:", payload);
          setWorkers(prev => prev.map(w => {
            if (w.worker_id !== payload.worker_id) return w;
            const updatedHistory = [...w.tool_history];
            const lastTool = updatedHistory[updatedHistory.length - 1];
            if (lastTool && lastTool.tool_name === payload.tool_name) {
              lastTool.status = payload.success ? "success" : "error";
              lastTool.result = payload.result;
            }
            return {
              ...w,
              current_tool: undefined,
              tool_history: updatedHistory,
            };
          }));
        },
        onWorkerCompleted: (payload: WorkerCompletedPayload) => {
          console.log("[Worker] Completed:", payload);
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? {
                  ...w,
                  status: payload.success ? "completed" as const : "error" as const,
                  files: payload.files,
                  summary: payload.summary,
                  error: payload.error,
                  current_tool: undefined,
                }
              : w
          ));
        },
        onWorkerError: (payload: WorkerErrorPayload) => {
          console.log("[Worker] Error:", payload);
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? { ...w, status: "error" as const, error: payload.error, current_tool: undefined }
              : w
          ));
        },
        onWorkerIteration: (payload: WorkerIterationPayload) => {
          console.log("[Worker] Iteration:", payload);
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? {
                  ...w,
                  iteration: payload.iteration,
                  max_iterations: payload.max_iterations,
                }
              : w
          ));
        },
        onWorkerTextDelta: (payload: WorkerTextDeltaPayload) => {
          // Append reasoning text delta to worker state
          setWorkers(prev => prev.map(w =>
            w.worker_id === payload.worker_id
              ? {
                  ...w,
                  reasoning_text: (w.reasoning_text || "") + payload.text,
                }
              : w
          ));
        },
        // State sync: respond to backend's state refresh request
        onRequestStateRefresh: (requestId: string) => {
          console.log("[WebSocket] State refresh requested:", requestId);
          const getState = getWebContainerStateRef.current;
          const wsClient = clientRef.current;
          if (getState && wsClient) {
            const freshState = getState();
            console.log(`[WebSocket] Sending fresh state, version: ${freshState.version || 0}`);
            wsClient.sendStateRefreshResponse(requestId, freshState);
          } else {
            console.warn("[WebSocket] Cannot refresh state: missing handler or client");
          }
        },
        onDone: () => {
          // Finalize the message
          const blocksBuilder = blocksBuilderRef.current;
          const currentMessage = currentMessageRef.current;
          const currentMessages = messagesRef.current;

          if (currentMessage) {
            const finalMessage: ChatMessage = {
              ...currentMessage,
              contentBlocks: [...blocksBuilder],
              content: blocksBuilder
                .filter((b): b is ContentBlock & { type: "text" } => b.type === "text")
                .map((b) => b.content)
                .join(""),
              isThinking: false,
            };

            // Update messages with final version
            const updated = [...currentMessages];
            const idx = updated.findIndex((m) => m.id === currentMessage.id);
            if (idx >= 0) {
              updated[idx] = finalMessage;
            }
            messagesRef.current = updated; // Keep ref in sync
            onMessagesChangeRef.current(updated);
          }

          // Reset state
          blocksBuilderRef.current = [];
          currentMessageRef.current = null;
          setIsLoading(false);
          setCurrentTool(null);
          // Keep workers visible after completion for debugging
          // They will be cleared when user sends next message
        },
      });

      clientRef.current = client;

      // Connect
      setConnectionState("connecting");
      try {
        await client.connect();
      } catch {
        // Connection failed - backend may not be running
        // Don't log error to avoid red console messages
        setConnectionState("error");
      }
    };

    initConnection();

    // Cleanup on unmount
    return () => {
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, sandboxId]); // Reconnect when mode or sandboxId changes

  // Helper to update current message in the message list
  const updateCurrentMessage = useCallback(() => {
    const blocksBuilder = blocksBuilderRef.current;
    const currentMessage = currentMessageRef.current;
    const currentMessages = messagesRef.current;

    if (!currentMessage) return;

    const updatedMessage: ChatMessage = {
      ...currentMessage,
      contentBlocks: [...blocksBuilder],
      isThinking: true,
    };

    const updated = [...currentMessages];
    const idx = updated.findIndex((m) => m.id === currentMessage.id);
    if (idx >= 0) {
      updated[idx] = updatedMessage;
      messagesRef.current = updated; // Keep ref in sync
      onMessagesChangeRef.current(updated);
    }
  }, []); // No dependencies - uses refs

  // Handle send message via WebSocket
  const handleSend = useCallback(
    async (content: string, images?: string[]) => {
      const client = clientRef.current;

      // Check WebSocket connection
      if (!client || !client.isConnected()) {
        // Try to reconnect
        if (client) {
          setConnectionState("connecting");
          try {
            await client.connect();
          } catch (error) {
            console.error("[WebSocket] Reconnection failed:", error);
            setConnectionState("error");

            // Show error message
            const errorMessage: ChatMessage = {
              id: generateId(),
              role: "system",
              content: `❌ **WebSocket Connection Failed**\n\n` +
                       `Unable to connect to the backend server.\n\n` +
                       `Please check:\n` +
                       `1. Backend service is running\n` +
                       `2. WebSocket endpoint is accessible\n` +
                       `3. Network connection is stable`,
              timestamp: Date.now(),
            };
            onMessagesChange([...messages, errorMessage]);
            return;
          }
        } else {
          const errorMessage: ChatMessage = {
            id: generateId(),
            role: "system",
            content: `❌ **WebSocket Not Initialized**\n\nPlease refresh the page.`,
            timestamp: Date.now(),
          };
          onMessagesChange([...messages, errorMessage]);
          return;
        }
      }

      // Clear file diffs from previous Agent interactions
      onClearFileDiffs?.();

      // Clear workers from previous interaction
      setWorkers([]);

      // Reset scroll state: when user sends a message, always scroll to bottom
      // 重置滚动状态：用户发送消息时，始终滚动到底部
      isAtBottomRef.current = true;

      // Add user message (with optional images)
      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content,
        timestamp: Date.now(),
        images, // Attach images if provided
      };

      // Auto-generate project name on first message (parallel, fire-and-forget)
      // 第一条消息时并行生成项目名称
      if (!namingTriggeredRef.current && onProjectNameGenerated) {
        const hasUserMessages = messages.some((m) => m.role === "user");
        if (!hasUserMessages) {
          namingTriggeredRef.current = true;

          // If we have a selected source, use its title directly
          // 如果有选中的 source，直接使用其标题
          if (selectedSource?.title && selectedSource.title !== "Untitled") {
            // Extract domain or clean up title for project name
            const cleanTitle = selectedSource.title
              .replace(/\s*[|\-–—]\s*.+$/, "")  // Remove suffix like "| Company Name"
              .trim()
              .slice(0, 50);  // Limit length
            onProjectNameGenerated(cleanTitle || selectedSource.title);
          } else {
            // Fire and forget - don't block the main flow
            generateProjectName(content).then((name) => {
              if (name) {
                onProjectNameGenerated(name);
              }
            });
          }
        }
      }

      // Create assistant message placeholder
      const assistantMessage: ChatMessage = {
        id: generateId(),
        role: "assistant",
        content: "",
        timestamp: Date.now(),
        contentBlocks: [],
        isThinking: true,
      };

      // Update messages
      const newMessages = [...messages, userMessage, assistantMessage];
      messagesRef.current = newMessages; // Update ref immediately for callbacks
      onMessagesChange(newMessages);

      // Store reference for callbacks
      blocksBuilderRef.current = [];
      currentMessageRef.current = assistantMessage;

      // Set loading state
      setIsLoading(true);
      setStartTime(Date.now());
      setCurrentTool(null);

      // Send message based on mode
      if (mode === "boxlite") {
        // BoxLite mode: use BoxLite state and client
        const boxliteClient = client as BoxLiteAgentClient;
        const currentBoxLiteState = boxliteStateRef.current;
        boxliteClient.sendChat(content, currentBoxLiteState, selectedSource?.id, images);
      } else {
        // WebContainer mode: use WebContainer state and client
        const wcClient = client as NextingAgentClient;
        const wcState = getWebContainerState?.() || {
          status: "idle" as const,
          files: {},
          activeFile: null,
          terminals: [],
          activeTerminalId: null,
          previewUrl: null,
          preview: {
            url: null,
            isLoading: false,
            hasError: false,
            consoleMessages: [],
            viewport: { width: 1280, height: 720 },
          },
          error: null,
          fileDiffs: {},
          version: 0,
          imageUrlMapping: {},
        };

        // Extract recent errors from system messages (within last 60 seconds)
        // These are preview/build errors that Agent should be aware of
        const recentErrors = messages
          .filter(m =>
            m.role === "system" &&
            (m.content.includes("Error") || m.content.includes("error") || m.content.includes("⚠️")) &&
            Date.now() - m.timestamp < 60000  // Last 60 seconds
          )
          .map(m => m.content)
          .slice(-5);  // Limit to last 5 errors to avoid too much context

        // Send message via WebSocket (include selectedSource.id, recent errors, and images for context)
        wcClient.sendChat(content, wcState, selectedSource?.id, recentErrors, images);
      }
    },
    [messages, onMessagesChange, getWebContainerState, onClearFileDiffs, generateId, selectedSource, mode]
  );

  // Auto-send message when shouldAutoSend becomes true
  const autoSendTriggeredRef = useRef(false);
  useEffect(() => {
    if (
      shouldAutoSend &&
      !autoSendTriggeredRef.current &&
      connectionState === "connected" &&
      selectedSource &&
      !isLoading
    ) {
      console.log("[AutoSend] Triggering auto-send:", autoSendMessage);
      autoSendTriggeredRef.current = true;
      handleSend(autoSendMessage);
      onAutoSendComplete?.();
    }
  }, [shouldAutoSend, connectionState, selectedSource, isLoading, autoSendMessage, handleSend, onAutoSendComplete]);

  return (
    <div
      data-testid="chat-panel"
      className={cn(
        "flex flex-col h-full",
        "bg-white dark:bg-black",
        "border-r border-neutral-200 dark:border-neutral-800",
        className
      )}
    >
      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-3 px-4 py-2.5 flex-shrink-0",
          "border-b border-neutral-200 dark:border-neutral-800",
          "bg-white dark:bg-black"
        )}
      >
        {/* Logo */}
        <img
          src="/logo-light.svg"
          alt="Nexting Logo"
          className="w-5 h-5 object-contain dark:hidden flex-shrink-0"
        />
        <img
          src="/logo-dark.svg"
          alt="Nexting Logo"
          className="w-5 h-5 object-contain hidden dark:block flex-shrink-0"
        />
        <div className="flex-1">
          <h2 className="text-xs font-medium text-neutral-900 dark:text-white">
            Nexting Agent
          </h2>
        </div>
        {/* Connection Status */}
        <div className="flex items-center gap-1.5">
          {connectionState === "connected" ? (
            <Wifi className="h-3 w-3 text-green-500" />
          ) : connectionState === "connecting" ? (
            <Loader2 className="h-3 w-3 animate-spin text-amber-500" />
          ) : (
            <WifiOff className="h-3 w-3 text-red-500" />
          )}
          <span className={cn(
            "text-[10px]",
            connectionState === "connected" && "text-green-600 dark:text-green-400",
            connectionState === "connecting" && "text-amber-600 dark:text-amber-400",
            (connectionState === "disconnected" || connectionState === "error") && "text-red-600 dark:text-red-400"
          )}>
            {connectionState === "connected" ? "Connected" :
             connectionState === "connecting" ? "Connecting..." :
             connectionState === "error" ? "Error" : "Disconnected"}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 space-y-3 bg-white dark:bg-black scrollbar-thin"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <h3 className="text-base font-medium text-neutral-900 dark:text-white mb-1.5">
              Clone any webpage you want
            </h3>
            <p className="text-xs text-neutral-500 dark:text-neutral-500 max-w-xs">
              Select a source from the Sources panel and let the agent create a pixel-perfect clone for you.
            </p>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <MessageItem key={message.id} message={message} workers={workers} />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>


      {/* Selected Source Indicator - Fixed position above input, collapsible */}
      {selectedSource && (
        <div
          className={cn(
            "flex-shrink-0 mx-3 mb-0 rounded-t-lg",
            "bg-emerald-50 dark:bg-emerald-900/20",
            "border border-b-0 border-emerald-200 dark:border-emerald-700",
            // Collapsed: minimal padding, Expanded: normal padding
            isSourceCollapsed ? "px-2 py-1" : "px-3 py-2"
          )}
        >
          {isSourceCollapsed ? (
            // Collapsed view - single line with expand button
            <button
              onClick={() => setIsSourceCollapsed(false)}
              className="flex items-center gap-1.5 w-full text-left hover:opacity-80 transition-opacity"
            >
              <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
              <span className="text-[11px] text-emerald-700 dark:text-emerald-400 truncate flex-1">
                Source: {selectedSource.title}
              </span>
              <ChevronRight className="h-3 w-3 text-emerald-500 flex-shrink-0" />
            </button>
          ) : (
            // Expanded view - full details
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-emerald-700 dark:text-emerald-400 flex items-center gap-1">
                  <Check className="h-3 w-3 flex-shrink-0" />
                  <span className="truncate">Source: {selectedSource.title}</span>
                </p>
                <p className="text-[10px] text-emerald-600 dark:text-emerald-500 truncate mt-0.5">
                  {selectedSource.url}
                </p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                {/* Collapse button */}
                <button
                  onClick={() => setIsSourceCollapsed(true)}
                  className={cn(
                    "p-1 rounded transition-colors",
                    "text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300",
                    "hover:bg-emerald-100 dark:hover:bg-emerald-800/30"
                  )}
                  title="Collapse"
                >
                  <ChevronDown className="h-3 w-3" />
                </button>
                {/* Clear button - only show when not loading */}
                {!isLoading && onClearSource && (
                  <button
                    onClick={onClearSource}
                    className={cn(
                      "p-1 rounded transition-colors",
                      "text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300",
                      "hover:bg-emerald-100 dark:hover:bg-emerald-800/30"
                    )}
                    title="Clear source selection"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Input - V0 style */}
      <div className={cn(
        "flex-shrink-0 p-3 bg-white dark:bg-black",
        // Adjust top padding when source indicator is shown
        selectedSource && "pt-0"
      )}>
        <div className={cn(
          selectedSource && "rounded-t-none border-t-0"
        )}>
          <ChatInput onSend={handleSend} isLoading={isLoading} />
        </div>
      </div>
    </div>
  );
}
