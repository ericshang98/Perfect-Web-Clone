/**
 * Showcase/Gallery Types
 *
 * Types for the showcase replay system that displays
 * pre-recorded agent sessions.
 */

// ============================================
// Replay Event Types
// ============================================

export type ReplayEventType =
  | 'agent_thinking'      // Agent 思考/文字输出
  | 'tool_call'           // 工具调用
  | 'tool_result'         // 工具结果
  | 'worker_spawned'      // Worker 创建
  | 'worker_progress'     // Worker 进度
  | 'worker_completed'    // Worker 完成
  | 'file_written'        // 文件写入
  | 'preview_ready'       // 预览就绪
  | 'error'               // 错误

export interface BaseReplayEvent {
  type: ReplayEventType
  timestamp: number  // 相对于开始的毫秒数
}

export interface AgentThinkingEvent extends BaseReplayEvent {
  type: 'agent_thinking'
  content: string
}

export interface ToolCallEvent extends BaseReplayEvent {
  type: 'tool_call'
  tool_name: string
  tool_input: Record<string, unknown>
}

export interface ToolResultEvent extends BaseReplayEvent {
  type: 'tool_result'
  tool_name: string
  success: boolean
  result: string
}

export interface WorkerSpawnedEvent extends BaseReplayEvent {
  type: 'worker_spawned'
  workers: Array<{
    worker_id: string
    section_name: string
    display_name: string
  }>
}

export interface WorkerProgressEvent extends BaseReplayEvent {
  type: 'worker_progress'
  worker_id: string
  section_name: string
  status: 'started' | 'completed' | 'failed'
  file_path?: string
}

export interface WorkerCompletedEvent extends BaseReplayEvent {
  type: 'worker_completed'
  worker_id: string
  section_name: string
  success: boolean
  files_written: string[]
}

export interface FileWrittenEvent extends BaseReplayEvent {
  type: 'file_written'
  path: string
  content: string
  size: number
}

export interface PreviewReadyEvent extends BaseReplayEvent {
  type: 'preview_ready'
  url: string
}

export interface ErrorEvent extends BaseReplayEvent {
  type: 'error'
  message: string
}

export type ReplayEvent =
  | AgentThinkingEvent
  | ToolCallEvent
  | ToolResultEvent
  | WorkerSpawnedEvent
  | WorkerProgressEvent
  | WorkerCompletedEvent
  | FileWrittenEvent
  | PreviewReadyEvent
  | ErrorEvent

// ============================================
// Showcase Data Types
// ============================================

export interface ShowcaseMeta {
  id: string
  name: string
  description: string
  source_url: string
  preview_image: string
  created_at: string
  stats: {
    sections: number
    files: number
    duration_seconds: number
  }
  tags?: string[]
}

export interface ShowcaseReplay {
  version: string
  recorded_at: string
  events: ReplayEvent[]
  total_duration_ms: number
}

export interface ShowcaseFiles {
  files: Record<string, string>  // path -> content
}

export interface Showcase {
  meta: ShowcaseMeta
  replay: ShowcaseReplay
  files: ShowcaseFiles
}

// ============================================
// Replay Player State
// ============================================

export interface ReplayPlayerState {
  // Playback state
  isPlaying: boolean
  isPaused: boolean
  isComplete: boolean

  // Progress
  currentEventIndex: number
  totalEvents: number
  progress: number  // 0-1
  elapsedTime: number  // ms

  // Current display
  currentEvent: ReplayEvent | null
  messages: ReplayMessage[]
  files: Record<string, string>
  workerStatuses: Record<string, WorkerStatus>

  // Controls
  playbackSpeed: number  // 1, 2, 3
}

export interface ReplayMessage {
  id: string
  type: 'agent' | 'tool' | 'system'
  content: string
  timestamp: number
  toolName?: string
  toolResult?: string
}

export interface WorkerStatus {
  worker_id: string
  section_name: string
  display_name: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  files_written: string[]
}

// ============================================
// Gallery Props
// ============================================

export interface ShowcaseCardProps {
  showcase: ShowcaseMeta
  onClick: () => void
}

export interface ShowcaseGalleryProps {
  showcases: ShowcaseMeta[]
  onSelect: (id: string) => void
}
