/**
 * BoxLite Types
 *
 * TypeScript types for BoxLite sandbox operations.
 * These match the backend models but are adapted for frontend use.
 */

// ============================================
// Enums
// ============================================

export type SandboxStatus =
  | "creating"
  | "booting"
  | "ready"
  | "running"
  | "stopped"
  | "error";

export type ToolType =
  // File operations
  | "write_file"
  | "read_file"
  | "delete_file"
  | "create_directory"
  | "rename_file"
  | "edit_file"
  | "list_files"
  // Terminal operations
  | "shell"
  | "run_command"
  | "install_dependencies"
  | "start_dev_server"
  | "stop_server"
  // Diagnostic operations
  | "get_state"
  | "get_preview_status"
  | "verify_changes"
  | "get_build_errors"
  | "get_visual_summary";

// ============================================
// File Types
// ============================================

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size?: number;
  modified_at?: string;
}

export interface FileContent {
  path: string;
  content: string;
}

// ============================================
// Terminal Types
// ============================================

export interface TerminalSession {
  id: string;
  name: string;
  is_running: boolean;
  command?: string;
  exit_code?: number;
  created_at: string;
}

export interface ProcessOutput {
  terminal_id: string;
  data: string;
  stream: "stdout" | "stderr";
  timestamp: string;
}

export interface CommandResult {
  success: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
}

// ============================================
// Preview Types
// ============================================

export interface PreviewState {
  url?: string;
  is_loading: boolean;
  has_error: boolean;
  error_message?: string;
}

export interface ConsoleMessage {
  type: "log" | "info" | "warn" | "error" | "debug";
  args: any[];
  timestamp: string;
  stack?: string;
}

export interface BuildError {
  type: string;
  message: string;
  file?: string;
  line?: number;
  column?: number;
  frame?: string;
  stack?: string;
}

export interface VisualSummary {
  has_content: boolean;
  visible_element_count: number;
  text_preview: string;
  viewport: { width: number; height: number };
  body_size: { width: number; height: number };
  background_color?: string;
}

// ============================================
// Sandbox State
// ============================================

export interface BoxLiteSandboxState {
  sandbox_id: string;
  status: SandboxStatus;
  error?: string;

  // File system
  files: Record<string, string>;
  active_file?: string;

  // Terminals
  terminals: TerminalSession[];
  active_terminal_id?: string;

  // Preview
  preview_url?: string;
  preview: PreviewState;
  console_messages: ConsoleMessage[];

  // Port forwarding
  forwarded_ports: Record<number, string>;

  // Metadata
  created_at: string;
  updated_at: string;
}

// ============================================
// Tool Request/Response
// ============================================

export interface ToolRequest {
  tool_name: string;
  params: Record<string, any>;
  request_id?: string;
}

export interface ToolResponse {
  success: boolean;
  result: string;
  data?: Record<string, any>;
  error?: string;
  request_id?: string;
}

// ============================================
// WebSocket Messages
// ============================================

export type WSMessageType =
  // Client -> Server
  | "ping"
  | "state_request"
  | "execute_tool"
  | "write_file"
  | "run_command"
  | "start_dev_server"
  | "stop_dev_server"
  | "terminal_input"
  | "file_edit"        // NEW: 用户编辑文件
  | "file_save"        // NEW: 用户保存文件
  | "chat"
  | "execute_action"
  // Server -> Client
  | "pong"
  | "state_update"
  | "tool_result"
  | "terminal_output"
  | "file_written"     // 文件写入（实时同步）
  | "file_deleted"     // NEW: 文件删除
  | "command_result"
  | "dev_server_started"
  | "dev_server_stopped"
  | "preview_update"   // NEW: 预览更新
  | "action_result"
  | "error"
  | "text";

export interface WSMessage {
  type: WSMessageType;
  payload: Record<string, any>;
}

// ============================================
// Chat Message Types
// ============================================

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
}

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, any>;
}

export interface ToolResult {
  id: string;
  toolName: string;
  success: boolean;
  result: string;
  data?: Record<string, any>;
}

// ============================================
// File Diff Types
// ============================================

export interface FileDiff {
  path: string;
  oldContent?: string;
  newContent: string;
  timestamp: number;
}

export interface FileDiffState {
  diffs: Record<string, FileDiff>;
  selectedPath?: string;
}

// ============================================
// Agent Log Entry
// ============================================

export interface AgentLogEntry {
  type: "command" | "output" | "error" | "info" | "file";
  content: string;
  timestamp: number;
}

// ============================================
// Hook Return Type
// ============================================

export interface UseBoxLiteReturn {
  // State
  state: BoxLiteSandboxState | null;
  isConnected: boolean;
  isInitialized: boolean;
  error: string | null;

  // Sandbox lifecycle
  initialize: () => Promise<void>;
  cleanup: () => Promise<void>;

  // External state update (for Agent WebSocket integration)
  updateState: (newState: BoxLiteSandboxState) => void;

  // File operations
  writeFile: (path: string, content: string) => Promise<boolean>;
  readFile: (path: string) => Promise<string | null>;
  deleteFile: (path: string) => Promise<boolean>;
  listFiles: (path?: string) => Promise<FileEntry[]>;

  // Command operations
  runCommand: (command: string, background?: boolean) => Promise<CommandResult>;
  startDevServer: () => Promise<boolean>;
  stopDevServer: () => Promise<boolean>;

  // Terminal
  getTerminalOutput: (terminalId?: string, lines?: number) => string[];
  sendTerminalInput: (terminalId: string, input: string) => Promise<boolean>;

  // Tool execution
  executeTool: (
    toolName: string,
    params: Record<string, any>
  ) => Promise<ToolResponse>;

  // Diagnostics
  verifyChanges: () => Promise<ToolResponse>;
  getBuildErrors: () => Promise<BuildError[]>;

  // Agent logs
  agentLogs: AgentLogEntry[];
  addAgentLog: (log: AgentLogEntry) => void;
  clearAgentLogs: () => void;
  restoreAgentLogs: (logs: AgentLogEntry[]) => void;

  // File diffs
  fileDiffs: FileDiffState;
  clearFileDiff: (path: string) => void;
}
