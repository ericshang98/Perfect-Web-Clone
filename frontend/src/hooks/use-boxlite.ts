"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type {
  BoxLiteSandboxState,
  FileEntry,
  CommandResult,
  ToolResponse,
  BuildError,
  AgentLogEntry,
  FileDiffState,
  FileDiff,
  ProcessOutput,
  UseBoxLiteReturn,
  WSMessage,
} from "@/types/boxlite";

// ============================================
// Constants
// ============================================

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5100";
const WS_BASE = API_BASE.replace("http", "ws");

const MAX_AGENT_LOGS = 500;
const RECONNECT_INTERVAL = 3000;
const PING_INTERVAL = 30000;

// Storage key for sandbox ID persistence
const SANDBOX_ID_STORAGE_KEY = "boxlite_sandbox_id";

// ============================================
// Hook: useBoxLite
// ============================================

export interface UseBoxLiteOptions {
  /**
   * Auto-initialize sandbox on mount
   */
  autoInit?: boolean;

  /**
   * Callback when terminal output is received
   */
  onTerminalOutput?: (output: ProcessOutput) => void;

  /**
   * Callback when state updates
   */
  onStateUpdate?: (state: BoxLiteSandboxState) => void;

  /**
   * Callback when file is written
   */
  onFileWritten?: (path: string) => void;
}

export function useBoxLite(options: UseBoxLiteOptions = {}): UseBoxLiteReturn {
  const { autoInit = true, onTerminalOutput, onStateUpdate, onFileWritten } =
    options;

  // State
  const [state, setState] = useState<BoxLiteSandboxState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLogEntry[]>([]);
  const [fileDiffs, setFileDiffs] = useState<FileDiffState>({
    diffs: {},
    selectedPath: undefined,
  });

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const sandboxIdRef = useRef<string | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const terminalOutputRef = useRef<Record<string, string[]>>({});
  const pendingRequestsRef = useRef<
    Map<string, { resolve: (value: any) => void; reject: (error: any) => void }>
  >(new Map());

  // ============================================
  // Agent Logs (defined early for use in other callbacks)
  // ============================================

  const addAgentLog = useCallback((log: AgentLogEntry) => {
    setAgentLogs((prev) => {
      // 去重：检查最近10条日志是否有相同内容
      const recentLogs = prev.slice(-10);
      const contentKey = log.content.slice(0, 200);
      const isDuplicate = recentLogs.some(
        (existingLog) => existingLog.content.slice(0, 200) === contentKey
      );
      if (isDuplicate) {
        return prev; // 跳过重复内容
      }

      const newLogs = [...prev, log];
      if (newLogs.length > MAX_AGENT_LOGS) {
        return newLogs.slice(-MAX_AGENT_LOGS);
      }
      return newLogs;
    });
  }, []);

  const clearAgentLogs = useCallback(() => {
    setAgentLogs([]);
  }, []);

  // Restore agent logs from checkpoint
  const restoreAgentLogs = useCallback((logs: AgentLogEntry[]) => {
    setAgentLogs(logs);
  }, []);

  // ============================================
  // WebSocket Management
  // ============================================

  const connectWebSocket = useCallback((sandboxId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const wsUrl = `${WS_BASE}/api/boxlite/ws/${sandboxId}`;
    console.log(`[BoxLite] Connecting to ${wsUrl}`);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[BoxLite] WebSocket connected");
      setIsConnected(true);
      setError(null);

      // Start ping interval
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        handleMessage(message);
      } catch (e) {
        console.error("[BoxLite] Failed to parse message:", e);
      }
    };

    ws.onerror = (event) => {
      console.error("[BoxLite] WebSocket error:", event);
      setError("WebSocket connection error");
    };

    ws.onclose = () => {
      console.log("[BoxLite] WebSocket closed");
      setIsConnected(false);

      // Clear ping interval
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }

      // Attempt reconnection
      if (sandboxIdRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          if (sandboxIdRef.current) {
            connectWebSocket(sandboxIdRef.current);
          }
        }, RECONNECT_INTERVAL);
      }
    };
  }, []);

  const handleMessage = useCallback(
    (message: WSMessage) => {
      const { type, payload } = message;

      switch (type) {
        case "pong":
          // Heartbeat response
          break;

        case "state_update":
          const newState = payload as BoxLiteSandboxState;
          setState(newState);
          onStateUpdate?.(newState);
          break;

        case "terminal_output":
          const output = payload as ProcessOutput;
          // Store terminal output
          if (!terminalOutputRef.current[output.terminal_id]) {
            terminalOutputRef.current[output.terminal_id] = [];
          }
          terminalOutputRef.current[output.terminal_id].push(output.data);
          onTerminalOutput?.(output);

          // Add to agent logs
          addAgentLog({
            type: "output",
            content: output.data,
            timestamp: Date.now(),
          });
          break;

        case "tool_result":
          const requestId = payload.request_id;
          if (requestId && pendingRequestsRef.current.has(requestId)) {
            const { resolve } = pendingRequestsRef.current.get(requestId)!;
            pendingRequestsRef.current.delete(requestId);
            resolve({
              success: payload.success,
              result: payload.result,
              data: payload.data,
              error: payload.error,
            });
          }
          break;

        case "file_written":
          const { path, success } = payload;
          if (success) {
            onFileWritten?.(path);
            addAgentLog({
              type: "file",
              content: `Wrote file: ${path}`,
              timestamp: Date.now(),
            });
          }
          break;

        case "command_result":
          addAgentLog({
            type: payload.success ? "output" : "error",
            content: payload.stdout || payload.stderr,
            timestamp: Date.now(),
          });
          break;

        case "dev_server_started":
          if (payload.success) {
            addAgentLog({
              type: "info",
              content: `Dev server started: ${payload.preview_url}`,
              timestamp: Date.now(),
            });
          }
          break;

        case "error":
          console.error("[BoxLite] Error:", payload.message);
          setError(payload.message);
          break;

        default:
          console.log("[BoxLite] Unhandled message type:", type);
      }
    },
    [onStateUpdate, onTerminalOutput, onFileWritten]
  );

  const sendMessage = useCallback((message: WSMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn("[BoxLite] WebSocket not connected");
    }
  }, []);

  // ============================================
  // Sandbox Lifecycle
  // ============================================

  const initialize = useCallback(async () => {
    try {
      console.log("[BoxLite] Initializing sandbox...");
      setError(null);

      // Add initial log
      addAgentLog({
        type: "info",
        content: "Initializing sandbox...",
        timestamp: Date.now(),
      });

      let sandboxId: string | null = null;
      let isReconnect = false;

      // Step 1: Try to reconnect to existing sandbox (if ID exists in sessionStorage)
      const storedSandboxId = typeof window !== "undefined"
        ? sessionStorage.getItem(SANDBOX_ID_STORAGE_KEY)
        : null;

      if (storedSandboxId) {
        console.log("[BoxLite] Found stored sandbox ID, attempting reconnect:", storedSandboxId);
        addAgentLog({
          type: "info",
          content: `Found existing sandbox: ${storedSandboxId}, attempting reconnect...`,
          timestamp: Date.now(),
        });

        try {
          const reconnectResponse = await fetch(`${API_BASE}/api/boxlite/sandbox/reconnect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sandbox_id: storedSandboxId }),
          });

          if (reconnectResponse.ok) {
            const data = await reconnectResponse.json();
            sandboxId = data.sandbox_id;
            isReconnect = true;
            console.log("[BoxLite] Reconnected to existing sandbox:", sandboxId);
            addAgentLog({
              type: "info",
              content: `✓ Reconnected to sandbox: ${sandboxId} (files preserved)`,
              timestamp: Date.now(),
            });
          } else if (reconnectResponse.status === 404) {
            console.log("[BoxLite] Sandbox not found, will create new one");
            addAgentLog({
              type: "info",
              content: "Previous sandbox not found, creating new one...",
              timestamp: Date.now(),
            });
            // Clear invalid stored ID
            sessionStorage.removeItem(SANDBOX_ID_STORAGE_KEY);
          } else {
            console.warn("[BoxLite] Reconnect failed, will create new sandbox");
          }
        } catch (e) {
          console.warn("[BoxLite] Reconnect error, will create new sandbox:", e);
        }
      }

      // Step 2: If reconnect failed or no stored ID, create new sandbox
      if (!sandboxId) {
        // Clear ALL previous state for fresh start
        setAgentLogs([]);  // Clear logs
        terminalOutputRef.current = {};  // Clear terminal output
        setState(null);  // Clear state

        addAgentLog({
          type: "info",
          content: "Creating new sandbox...",
          timestamp: Date.now(),
        });

        const response = await fetch(`${API_BASE}/api/boxlite/sandbox`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });

        if (!response.ok) {
          throw new Error(`Failed to create sandbox: ${response.statusText}`);
        }

        const data = await response.json();
        sandboxId = data.sandbox_id;

        addAgentLog({
          type: "info",
          content: `Sandbox created: ${sandboxId}`,
          timestamp: Date.now(),
        });
      }

      // Step 3: Save sandbox ID to sessionStorage
      if (sandboxId && typeof window !== "undefined") {
        sessionStorage.setItem(SANDBOX_ID_STORAGE_KEY, sandboxId);
      }

      sandboxIdRef.current = sandboxId;

      // Connect WebSocket
      connectWebSocket(sandboxId!);

      setIsInitialized(true);
      console.log("[BoxLite] Sandbox initialized:", sandboxId);

      addAgentLog({
        type: "info",
        content: "WebSocket connected. Checking dev server status...",
        timestamp: Date.now(),
      });

      // Check dev server status and start if needed
      setTimeout(async () => {
        try {
          const stateResponse = await fetch(
            `${API_BASE}/api/boxlite/sandbox/${sandboxId}`
          );

          if (stateResponse.ok) {
            const currentState = await stateResponse.json();

            // If preview_url is already set, dev server is running
            if (currentState.preview_url) {
              addAgentLog({
                type: "info",
                content: `Dev server already running: ${currentState.preview_url}`,
                timestamp: Date.now(),
              });

              // Update state with current values
              setState((prev) => ({
                ...prev,
                ...currentState,
              }));
              return;
            }
          }

          // Dev server not running, start it
          addAgentLog({
            type: "info",
            content: "Starting dev server...",
            timestamp: Date.now(),
          });

          const startResponse = await fetch(
            `${API_BASE}/api/boxlite/sandbox/${sandboxId}/dev-server/start`,
            { method: "POST" }
          );

          if (startResponse.ok) {
            const startData = await startResponse.json();
            const previewUrl = startData.preview_url || "http://localhost:8080";

            addAgentLog({
              type: "info",
              content: `Dev server ready: ${previewUrl}`,
              timestamp: Date.now(),
            });

            setState((prev) => {
              if (!prev) return prev;
              return {
                ...prev,
                preview_url: previewUrl,
                preview: {
                  ...prev.preview,
                  url: previewUrl,
                  is_loading: false,
                },
                status: "running",
              };
            });
          } else {
            addAgentLog({
              type: "error",
              content: "Failed to start dev server",
              timestamp: Date.now(),
            });
          }
        } catch (e) {
          console.error("[BoxLite] Auto-start dev server failed:", e);
          addAgentLog({
            type: "error",
            content: `Failed to start dev server: ${e instanceof Error ? e.message : "Unknown error"}`,
            timestamp: Date.now(),
          });
        }
      }, 1000);

    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      console.error("[BoxLite] Initialization failed:", message);
      setError(message);
      addAgentLog({
        type: "error",
        content: `Initialization failed: ${message}`,
        timestamp: Date.now(),
      });
    }
  }, [connectWebSocket, addAgentLog]);

  const cleanup = useCallback(async () => {
    console.log("[BoxLite] Cleaning up...");

    // Clear intervals and timeouts
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close WebSocket (but don't delete sandbox in singleton mode)
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    // In singleton mode, we keep the sandbox running for reuse
    // The backend will reuse the same sandbox on next connection
    // Only clear the ref, don't delete the sandbox
    sandboxIdRef.current = null;

    setState(null);
    setIsConnected(false);
    setIsInitialized(false);
  }, []);

  // ============================================
  // File Operations
  // ============================================

  const writeFile = useCallback(
    async (path: string, content: string): Promise<boolean> => {
      if (!sandboxIdRef.current) return false;

      try {
        // Store old content for diff
        const oldContent = state?.files[path];

        // Send write request
        sendMessage({
          type: "write_file",
          payload: { path, content },
        });

        // Update local state optimistically
        setState((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            files: { ...prev.files, [path]: content },
          };
        });

        // Create file diff
        if (oldContent !== content) {
          setFileDiffs((prev) => ({
            ...prev,
            diffs: {
              ...prev.diffs,
              [path]: {
                path,
                oldContent,
                newContent: content,
                timestamp: Date.now(),
              },
            },
          }));
        }

        return true;
      } catch (e) {
        console.error("[BoxLite] Write file failed:", e);
        return false;
      }
    },
    [state, sendMessage]
  );

  const readFile = useCallback(
    async (path: string): Promise<string | null> => {
      // SSOT: Always fetch from server (disk is the single source of truth)
      // Do NOT use local state cache - it may be stale
      if (!sandboxIdRef.current) return null;

      try {
        const response = await fetch(
          `${API_BASE}/api/boxlite/sandbox/${sandboxIdRef.current}/file?path=${encodeURIComponent(path)}`
        );

        if (!response.ok) return null;

        const data = await response.json();
        return data.content;
      } catch (e) {
        console.error("[BoxLite] Read file failed:", e);
        return null;
      }
    },
    []  // No dependencies - always fetch fresh from server
  );

  const deleteFile = useCallback(
    async (path: string): Promise<boolean> => {
      return executeTool("delete_file", { path }).then((r) => r.success);
    },
    []
  );

  const listFiles = useCallback(
    async (path: string = "/"): Promise<FileEntry[]> => {
      if (!sandboxIdRef.current) return [];

      try {
        const response = await fetch(
          `${API_BASE}/api/boxlite/sandbox/${sandboxIdRef.current}/files?path=${encodeURIComponent(path)}`
        );

        if (!response.ok) return [];

        const data = await response.json();
        return data.entries;
      } catch (e) {
        console.error("[BoxLite] List files failed:", e);
        return [];
      }
    },
    []
  );

  // ============================================
  // Command Operations
  // ============================================

  const runCommand = useCallback(
    async (command: string, background = false): Promise<CommandResult> => {
      if (!sandboxIdRef.current) {
        return {
          success: false,
          exit_code: -1,
          stdout: "",
          stderr: "Sandbox not initialized",
          duration_ms: 0,
        };
      }

      addAgentLog({
        type: "command",
        content: `$ ${command}`,
        timestamp: Date.now(),
      });

      try {
        const response = await fetch(
          `${API_BASE}/api/boxlite/sandbox/${sandboxIdRef.current}/command`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command, background }),
          }
        );

        const result = await response.json();

        if (result.stdout) {
          addAgentLog({
            type: "output",
            content: result.stdout,
            timestamp: Date.now(),
          });
        }
        if (result.stderr) {
          addAgentLog({
            type: "error",
            content: result.stderr,
            timestamp: Date.now(),
          });
        }

        return result;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : "Command failed";
        return {
          success: false,
          exit_code: -1,
          stdout: "",
          stderr: errorMsg,
          duration_ms: 0,
        };
      }
    },
    []
  );

  const startDevServer = useCallback(async (): Promise<boolean> => {
    sendMessage({ type: "start_dev_server", payload: {} });
    return true;
  }, [sendMessage]);

  const stopDevServer = useCallback(async (): Promise<boolean> => {
    sendMessage({ type: "stop_dev_server", payload: {} });
    return true;
  }, [sendMessage]);

  // ============================================
  // Terminal Operations
  // ============================================

  const getTerminalOutput = useCallback(
    (terminalId?: string, lines = 50): string[] => {
      const id = terminalId || state?.active_terminal_id;
      if (!id) return [];

      const output = terminalOutputRef.current[id] || [];
      return output.slice(-lines);
    },
    [state]
  );

  const sendTerminalInput = useCallback(
    async (terminalId: string, input: string): Promise<boolean> => {
      sendMessage({
        type: "terminal_input",
        payload: { terminal_id: terminalId, input },
      });
      return true;
    },
    [sendMessage]
  );

  // ============================================
  // Tool Execution
  // ============================================

  const executeTool = useCallback(
    async (
      toolName: string,
      params: Record<string, any>
    ): Promise<ToolResponse> => {
      const requestId = `req-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

      return new Promise((resolve, reject) => {
        pendingRequestsRef.current.set(requestId, { resolve, reject });

        sendMessage({
          type: "execute_tool",
          payload: {
            tool_name: toolName,
            params,
            request_id: requestId,
          },
        });

        // Timeout after 60 seconds
        setTimeout(() => {
          if (pendingRequestsRef.current.has(requestId)) {
            pendingRequestsRef.current.delete(requestId);
            resolve({
              success: false,
              result: "",
              error: "Request timeout",
            });
          }
        }, 60000);
      });
    },
    [sendMessage]
  );

  // ============================================
  // Diagnostics
  // ============================================

  const verifyChanges = useCallback(async (): Promise<ToolResponse> => {
    return executeTool("verify_changes", {});
  }, [executeTool]);

  const getBuildErrors = useCallback(async (): Promise<BuildError[]> => {
    const result = await executeTool("get_build_errors", {});
    return result.data?.errors || [];
  }, [executeTool]);

  // ============================================
  // File Diffs
  // ============================================

  const clearFileDiff = useCallback((path: string) => {
    setFileDiffs((prev) => {
      const newDiffs = { ...prev.diffs };
      delete newDiffs[path];
      return { ...prev, diffs: newDiffs };
    });
  }, []);

  // ============================================
  // External State Update
  // ============================================

  /**
   * Update state from external source (e.g., Agent WebSocket state_update)
   * This allows the agent's state updates to sync with this hook's state
   */
  const updateState = useCallback((newState: BoxLiteSandboxState) => {
    console.log("[BoxLite] External state update received, files:", Object.keys(newState.files || {}).length, "preview_url:", newState.preview_url);
    setState(newState);
    onStateUpdate?.(newState);
  }, [onStateUpdate]);

  // ============================================
  // Effects
  // ============================================

  // Auto-initialize on mount
  useEffect(() => {
    if (autoInit) {
      initialize();
    }

    return () => {
      cleanup();
    };
  }, [autoInit, initialize, cleanup]);

  // ============================================
  // Return
  // ============================================

  return {
    // State
    state,
    isConnected,
    isInitialized,
    error,

    // Sandbox lifecycle
    initialize,
    cleanup,

    // External state update (for Agent WebSocket integration)
    updateState,

    // File operations
    writeFile,
    readFile,
    deleteFile,
    listFiles,

    // Command operations
    runCommand,
    startDevServer,
    stopDevServer,

    // Terminal
    getTerminalOutput,
    sendTerminalInput,

    // Tool execution
    executeTool,

    // Diagnostics
    verifyChanges,
    getBuildErrors,

    // Agent logs
    agentLogs,
    addAgentLog,
    clearAgentLogs,
    restoreAgentLogs,

    // File diffs
    fileDiffs,
    clearFileDiff,
  };
}

export default useBoxLite;
