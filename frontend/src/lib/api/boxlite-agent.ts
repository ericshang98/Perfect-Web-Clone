/**
 * Nexting Agent API Client (Sandbox Mode)
 *
 * WebSocket-based API for communicating with backend sandbox.
 *
 * Key features:
 * - Connects to sandbox backend (port 5100)
 * - No execute_action handling - tools execute on backend directly
 * - Receives state_update events for sandbox state sync
 */

import type { BoxLiteSandboxState } from "@/types/boxlite";

// ============================================
// Configuration
// ============================================

const BOXLITE_BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5100";
const WS_URL = BOXLITE_BACKEND_URL.replace(/^http/, "ws");
const API_BASE = `${BOXLITE_BACKEND_URL}/api/boxlite-agent`;

// ============================================
// Types
// ============================================

// Client -> Server messages
export type ClientMessageType = "chat" | "state_refresh" | "ping";

export interface ClientMessage {
  type: ClientMessageType;
  payload: Record<string, unknown>;
}

// Server -> Client messages
export type ServerMessageType =
  | "text"
  | "text_delta"
  | "tool_call"
  | "tool_result"
  | "state_update"
  | "file_written"     // NEW: 实时文件写入
  | "file_deleted"     // NEW: 文件删除
  | "terminal_output"  // NEW: 终端输出
  | "trigger_checkpoint_save"  // Backend requests frontend to save checkpoint
  | "error"
  | "done"
  | "pong"
  // Worker Agent events (Multi-Agent) - for future support
  | "worker_spawned"
  | "worker_started"
  | "worker_tool_call"
  | "worker_tool_result"
  | "worker_completed"
  | "worker_error"
  | "worker_iteration"
  | "worker_text_delta";

// File write payload
export interface FileWrittenPayload {
  worker_id?: string;
  path: string;
  content: string;
  size: number;
}

// Terminal output payload
export interface TerminalOutputPayload {
  terminal_id: string;
  data: string;
  stream: "stdout" | "stderr";
}

export interface ServerMessage {
  type: ServerMessageType;
  payload: Record<string, unknown>;
}

// Worker event payloads (same as nexting-agent)
export interface WorkerSpawnedPayload {
  worker_id: string;
  section_name: string;
  display_name?: string;
  task_description: string;
  input_data: {
    section_data_keys: string[];
    target_files: string[];
    has_layout_context: boolean;
    has_style_context: boolean;
    html_lines?: number;
    html_chars?: number;
    html_range?: { start: number; end: number } | null;
    char_start?: number;
    char_end?: number;
    estimated_tokens?: number;
    images_count?: number;
    links_count?: number;
  };
  total_workers: number;
}

export interface WorkerToolCallPayload {
  worker_id: string;
  section_name: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
}

export interface WorkerToolResultPayload {
  worker_id: string;
  section_name: string;
  tool_name: string;
  result: string;
  success: boolean;
}

export interface WorkerCompletedPayload {
  worker_id: string;
  section_name: string;
  success: boolean;
  files: string[];
  file_count: number;
  summary: string;
  error?: string;
}

export interface WorkerErrorPayload {
  worker_id: string;
  section_name: string;
  error: string;
}

export interface WorkerIterationPayload {
  worker_id: string;
  section_name: string;
  iteration: number;
  max_iterations: number;
}

export interface WorkerTextDeltaPayload {
  worker_id: string;
  section_name: string;
  text: string;
  iteration: number;
}

// WebSocket connection options
export interface BoxLiteWebSocketOptions {
  sandboxId: string;  // Required for BoxLite
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  onText?: (content: string) => void;
  onTextDelta?: (delta: string) => void;
  onToolCall?: (toolCall: { id: string; name: string; input: Record<string, unknown> }) => void;
  onToolResult?: (result: { id: string; success: boolean; result: string }) => void;
  onStateUpdate?: (state: BoxLiteSandboxState) => void;
  onDone?: () => void;
  // Real-time sync callbacks (NEW)
  onFileWritten?: (payload: FileWrittenPayload) => void;
  onFileDeleted?: (payload: { path: string }) => void;
  onTerminalOutput?: (payload: TerminalOutputPayload) => void;
  // Checkpoint save trigger (backend asks frontend to save with full data)
  onTriggerCheckpointSave?: (payload: { project_id: string; files_count: number }) => void;
  // Worker Agent event callbacks (Multi-Agent)
  onWorkerSpawned?: (payload: WorkerSpawnedPayload) => void;
  onWorkerStarted?: (payload: { worker_id: string; section_name: string }) => void;
  onWorkerToolCall?: (payload: WorkerToolCallPayload) => void;
  onWorkerToolResult?: (payload: WorkerToolResultPayload) => void;
  onWorkerCompleted?: (payload: WorkerCompletedPayload) => void;
  onWorkerError?: (payload: WorkerErrorPayload) => void;
  onWorkerIteration?: (payload: WorkerIterationPayload) => void;
  onWorkerTextDelta?: (payload: WorkerTextDeltaPayload) => void;
}

// ============================================
// WebSocket Client Class
// ============================================

export class BoxLiteAgentClient {
  private ws: WebSocket | null = null;
  private sandboxId: string;
  private options: BoxLiteWebSocketOptions;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 3;
  private pingInterval: NodeJS.Timeout | null = null;

  constructor(options: BoxLiteWebSocketOptions) {
    this.sandboxId = options.sandboxId;
    this.options = options;
  }

  // ============================================
  // Connection Management
  // ============================================

  /**
   * Connect to WebSocket server
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const url = `${WS_URL}/api/boxlite-agent/ws/${this.sandboxId}`;

      try {
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
          console.log("[Agent] WebSocket connected");
          this.reconnectAttempts = 0;
          this.startPing();
          this.options.onOpen?.();
          resolve();
        };

        this.ws.onclose = (event) => {
          console.log("[Agent] WebSocket closed:", event.code, event.reason);
          this.stopPing();
          this.options.onClose?.();

          // Auto-reconnect on unexpected close
          if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`[Agent] Reconnecting... (attempt ${this.reconnectAttempts})`);
            setTimeout(() => this.connect(), 1000 * this.reconnectAttempts);
          }
        };

        this.ws.onerror = (error) => {
          if (this.ws?.readyState !== WebSocket.OPEN) {
            console.warn("[Agent] WebSocket connection failed - is backend running?");
            this.options.onError?.(error);
            reject(error);
          }
        };

        this.ws.onmessage = (event) => {
          this.handleMessage(event.data);
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    this.stopPing();
    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  // ============================================
  // Message Sending
  // ============================================

  /**
   * Send message to server
   */
  private send(message: ClientMessage): void {
    if (!this.isConnected()) {
      console.error("[Agent] Not connected");
      return;
    }

    this.ws!.send(JSON.stringify(message));
  }

  /**
   * Send chat message
   * @param message - User's message
   * @param sandboxState - Current sandbox state (optional)
   * @param selectedSourceId - Selected source ID for context
   * @param images - Base64 encoded images to include with message
   */
  sendChat(
    message: string,
    sandboxState?: BoxLiteSandboxState | null,
    selectedSourceId?: string | null,
    images?: string[]
  ): void {
    this.send({
      type: "chat",
      payload: {
        message,
        sandbox_state: sandboxState ? this.formatState(sandboxState) : undefined,
        selected_source_id: selectedSourceId || undefined,
        images: images && images.length > 0 ? images : undefined,
      },
    });
  }

  /**
   * Request state refresh from server
   */
  requestStateRefresh(): void {
    this.send({
      type: "state_refresh",
      payload: {},
    });
  }

  // ============================================
  // Message Handling
  // ============================================

  /**
   * Handle incoming message
   */
  private handleMessage(data: string): void {
    try {
      const message: ServerMessage = JSON.parse(data);
      const { type, payload } = message;

      switch (type) {
        case "text":
          this.options.onText?.(payload.content as string);
          break;

        case "text_delta":
          this.options.onTextDelta?.(payload.delta as string);
          break;

        case "tool_call":
          this.options.onToolCall?.({
            id: payload.id as string,
            name: payload.name as string,
            input: payload.input as Record<string, unknown>,
          });
          break;

        case "tool_result":
          this.options.onToolResult?.({
            id: payload.id as string,
            success: payload.success as boolean,
            result: payload.result as string,
          });
          break;

        case "state_update":
          // Receive sandbox state updates from server
          this.options.onStateUpdate?.(payload as unknown as BoxLiteSandboxState);
          break;

        case "file_written":
          // Real-time file write notification
          this.options.onFileWritten?.(payload as unknown as FileWrittenPayload);
          break;

        case "file_deleted":
          // File deletion notification
          this.options.onFileDeleted?.(payload as { path: string });
          break;

        case "terminal_output":
          // Terminal output notification
          this.options.onTerminalOutput?.(payload as unknown as TerminalOutputPayload);
          break;

        case "trigger_checkpoint_save":
          // Backend requests frontend to save checkpoint with full conversation data
          this.options.onTriggerCheckpointSave?.(payload as { project_id: string; files_count: number });
          break;

        case "error":
          console.error("[Agent] Server error:", payload.error);
          break;

        case "done":
          this.options.onDone?.();
          break;

        case "pong":
          // Heartbeat response
          break;

        // Worker Agent events (Multi-Agent)
        case "worker_spawned":
          this.options.onWorkerSpawned?.(payload as unknown as WorkerSpawnedPayload);
          break;

        case "worker_started":
          this.options.onWorkerStarted?.(payload as { worker_id: string; section_name: string });
          break;

        case "worker_tool_call":
          this.options.onWorkerToolCall?.(payload as unknown as WorkerToolCallPayload);
          break;

        case "worker_tool_result":
          this.options.onWorkerToolResult?.(payload as unknown as WorkerToolResultPayload);
          break;

        case "worker_completed":
          this.options.onWorkerCompleted?.(payload as unknown as WorkerCompletedPayload);
          break;

        case "worker_error":
          this.options.onWorkerError?.(payload as unknown as WorkerErrorPayload);
          break;

        case "worker_iteration":
          this.options.onWorkerIteration?.(payload as unknown as WorkerIterationPayload);
          break;

        case "worker_text_delta":
          this.options.onWorkerTextDelta?.(payload as unknown as WorkerTextDeltaPayload);
          break;

        default:
          console.log("[Agent] Unknown message type:", type);
      }
    } catch (error) {
      console.error("[Agent] Failed to parse message:", error);
    }
  }

  // ============================================
  // Heartbeat
  // ============================================

  private startPing(): void {
    this.pingInterval = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: "ping", payload: {} });
      }
    }, 30000); // 30 seconds
  }

  private stopPing(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  // ============================================
  // Helper Methods
  // ============================================

  /**
   * Format sandbox state for backend
   */
  private formatState(state: BoxLiteSandboxState): Record<string, unknown> {
    return {
      sandbox_id: state.sandbox_id,
      status: state.status,
      files: state.files,
      active_file: state.active_file,
      terminals: state.terminals,
      active_terminal_id: state.active_terminal_id,
      preview_url: state.preview_url,
      preview: state.preview,
      console_messages: state.console_messages,
      error: state.error,
    };
  }

  /**
   * Get sandbox ID
   */
  getSandboxId(): string {
    return this.sandboxId;
  }
}

// ============================================
// Factory Function
// ============================================

/**
 * Create BoxLite Agent client
 */
export function createBoxLiteAgentClient(options: BoxLiteWebSocketOptions): BoxLiteAgentClient {
  return new BoxLiteAgentClient(options);
}

// ============================================
// Legacy API Functions (HTTP fallback)
// ============================================

/**
 * Check API health
 */
export async function checkBoxLiteHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json();
}
