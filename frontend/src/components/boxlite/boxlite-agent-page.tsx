"use client";

import React, { useState, useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { getSource } from "@/lib/api/sources";
import { cn } from "@/lib/utils";
import { useBoxLite } from "@/hooks/use-boxlite";
import { BoxLiteIDE } from "./boxlite-ide";
import { ProjectHeader } from "./project-header";
import { SourcePanel, type SavedSource } from "./source-panel";
import { CheckpointPanel } from "./checkpoint-panel";
import { AppSidebar } from "@/components/app-sidebar";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { NextingAgentChatPanel } from "@/components/agent/chat-panel";
import type { ChatMessage, ToolCall, ContentBlock } from "@/types/agent";
import type { BoxLiteSandboxState } from "@/types/boxlite";

// ============================================
// Types
// ============================================

interface SelectedSource {
  id: string;
  title: string;
  url: string;
  theme: "light" | "dark";
}

// ============================================
// Main BoxLite Agent Page
// ============================================

export function BoxLiteAgentPage() {
  // URL params for auto-clone flow
  const searchParams = useSearchParams();
  const sourceIdParam = searchParams.get("source");
  const themeParam = searchParams.get("theme") as "light" | "dark" | null;
  const autoCloneParam = searchParams.get("autoClone") === "true";
  // URL params for checkpoint restore (from gallery showcase)
  const checkpointParam = searchParams.get("checkpoint");
  const projectParam = searchParams.get("project");

  // Sandbox hook (BoxLite infra)
  const {
    state,
    isConnected,
    isInitialized,
    error,
    readFile,
    writeFile,
    runCommand,
    startDevServer,
    stopDevServer,
    getTerminalOutput,
    sendTerminalInput,
    executeTool,
    agentLogs,
    addAgentLog,
    clearAgentLogs,
    restoreAgentLogs,
    fileDiffs,
    clearFileDiff,
    updateState,  // For syncing Agent WebSocket state_update
  } = useBoxLite({
    autoInit: true,
    onFileWritten: (path) => {
      console.log("[Sandbox] File written:", path);
    },
  });

  // UI State
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [chatPanelWidth, setChatPanelWidth] = useState(380);
  const [showChatPanel, setShowChatPanel] = useState(true);
  const [showSourcePanel, setShowSourcePanel] = useState(false);
  const [showCheckpointPanel, setShowCheckpointPanel] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [selectedSource, setSelectedSource] = useState<SelectedSource | null>(null);
  const [isAgentLoading, setIsAgentLoading] = useState(false);
  const [checkpointProjectId, setCheckpointProjectId] = useState<string | null>(null);

  // Auto-clone flow state
  const [autoCloneTriggered, setAutoCloneTriggered] = useState(false);
  const [shouldAutoSend, setShouldAutoSend] = useState(false);

  // Auto-restore checkpoint flow state (from gallery showcase)
  const [autoRestoreTriggered, setAutoRestoreTriggered] = useState(false);

  // Restore checkpoint dialog state
  const [restoreDialogOpen, setRestoreDialogOpen] = useState(false);
  const [restoreDialogData, setRestoreDialogData] = useState<{
    checkpointId: string;
    projectId: string;
  } | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);

  // Resizer state
  const [isResizing, setIsResizing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Handle file selection
  const handleFileSelect = useCallback(
    async (path: string) => {
      setSelectedFile(path);
      const content = await readFile(path);
      setFileContent(content || "");
    },
    [readFile]
  );

  // Handle file save
  const handleSaveFile = useCallback(async () => {
    if (selectedFile && fileContent) {
      await writeFile(selectedFile, fileContent);
      addAgentLog({
        type: "file",
        content: `Saved: ${selectedFile}`,
        timestamp: Date.now(),
      });
    }
  }, [selectedFile, fileContent, writeFile, addAgentLog]);

  // Handle file creation
  const handleFileCreate = useCallback(
    async (path: string, content: string) => {
      await writeFile(path, content);
    },
    [writeFile]
  );

  // Handle file deletion
  const handleFileDelete = useCallback(
    async (path: string) => {
      await executeTool("delete_file", { path });
    },
    [executeTool]
  );

  // Handle terminal input
  const handleTerminalInput = useCallback(
    async (input: string) => {
      const terminalId = state?.active_terminal_id;
      if (terminalId) {
        await sendTerminalInput(terminalId, input);
      } else {
        await runCommand(input.trim());
      }
    },
    [state, sendTerminalInput, runCommand]
  );

  // Handle BoxLite state update from Agent WebSocket
  // This syncs the Agent's state_update events with the useBoxLite hook's state
  const handleBoxLiteStateUpdate = useCallback((newState: BoxLiteSandboxState) => {
    console.log("[BoxLiteAgentPage] Received state_update, syncing with hook");
    updateState(newState);
  }, [updateState]);

  // Handle clearing file diffs
  const handleClearFileDiffs = useCallback(() => {
    Object.keys(fileDiffs.diffs).forEach((path) => clearFileDiff(path));
  }, [fileDiffs.diffs, clearFileDiff]);

  // Create or get checkpoint project for a source
  // This is extracted to be reusable by both manual selection and auto-clone flow
  const ensureCheckpointProject = useCallback(async (
    sourceId: string,
    sourceTitle: string,
    sourceUrl: string
  ) => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_BOXLITE_API_URL || "http://localhost:5100";
      const response = await fetch(`${API_BASE}/api/checkpoints/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: sourceTitle || `Clone ${sourceId.slice(0, 8)}`,
          source_id: sourceId,
          source_url: sourceUrl,
        }),
      });
      if (response.ok) {
        const data = await response.json();
        if (data.success && data.project?.id) {
          setCheckpointProjectId(data.project.id);
          console.log("[Checkpoint] Project ready:", data.project.id);
          return data.project.id;
        }
      }
    } catch (e) {
      console.error("[Checkpoint] Failed to create/get project:", e);
    }
    return null;
  }, []);

  // Handle source selection
  const handleSelectSource = useCallback(async (source: SavedSource) => {
    setSelectedSource({
      id: source.id,
      title: source.page_title || "Untitled",
      url: source.source_url,
      theme: source.metadata?.theme || "light",
    });

    // Create checkpoint project for this source
    await ensureCheckpointProject(
      source.id,
      source.page_title || "Untitled",
      source.source_url
    );
  }, [ensureCheckpointProject]);

  // Handle manual checkpoint save
  const handleSaveCheckpoint = useCallback(async () => {
    if (!checkpointProjectId || !state) return;

    try {
      const API_BASE = process.env.NEXT_PUBLIC_BOXLITE_API_URL || "http://localhost:5100";

      // Save FULL message data including tool calls and content blocks
      const fullConversation = messages.map(m => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
        toolCalls: m.toolCalls || [],
        contentBlocks: m.contentBlocks || [],
        isThinking: m.isThinking,
        images: m.images,
      }));

      // Generate checkpoint name with project name and timestamp
      const displayName = projectName || selectedSource?.title || "Project";
      const timestamp = new Date().toLocaleTimeString();
      const checkpointName = `${displayName} - Manual save (${timestamp})`;

      const response = await fetch(`${API_BASE}/api/checkpoints/projects/${checkpointProjectId}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: checkpointName,
          conversation: fullConversation,
          files: state.files || {},
          metadata: {
            manual: true,
            source_id: selectedSource?.id,
            project_name: displayName,
            agent_logs: agentLogs.slice(-100), // Save last 100 agent logs
          },
        }),
      });
      if (response.ok) {
        console.log("[Checkpoint] Manual checkpoint saved:", checkpointName);
        // Trigger refresh in checkpoint panel
      }
    } catch (e) {
      console.error("[Checkpoint] Failed to save:", e);
    }
  }, [checkpointProjectId, state, messages, selectedSource, agentLogs, projectName]);

  // Handle checkpoint restore - opens confirmation dialog
  const handleRestoreCheckpoint = useCallback((checkpointId: string, projectId: string) => {
    // Use provided projectId or fall back to current project
    const targetProjectId = projectId || checkpointProjectId;
    if (!targetProjectId) {
      alert("No project ID provided for restore");
      return;
    }

    // Open confirmation dialog
    setRestoreDialogData({ checkpointId, projectId: targetProjectId });
    setRestoreDialogOpen(true);
  }, [checkpointProjectId]);

  // Actually perform the restore after user confirms
  const performRestore = useCallback(async () => {
    if (!restoreDialogData) return;

    const { checkpointId, projectId: targetProjectId } = restoreDialogData;
    setIsRestoring(true);

    try {
      const API_BASE = process.env.NEXT_PUBLIC_BOXLITE_API_URL || "http://localhost:5100";
      const sandboxId = state?.sandbox_id || "default";

      console.log("[Checkpoint] Calling backend restore API...");
      console.log("[Checkpoint] Sandbox ID:", sandboxId);
      console.log("[Checkpoint] Project ID:", targetProjectId);
      console.log("[Checkpoint] Checkpoint ID:", checkpointId);

      // 1. Call backend restore API (writes files to sandbox, restarts dev server)
      const response = await fetch(
        `${API_BASE}/api/boxlite/sandbox/${sandboxId}/restore`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: targetProjectId,
            checkpoint_id: checkpointId,
          }),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Backend restore failed: ${response.status} ${errorText}`);
      }

      const data = await response.json();
      if (!data.success) {
        throw new Error("Backend restore returned failure");
      }

      console.log("[Checkpoint] Backend restore successful:", data.message);
      const checkpoint = data.checkpoint;

      // 2. Store conversation + metadata in sessionStorage for post-reload restore
      const restoreData = {
        conversation: checkpoint.conversation || [],
        agentLogs: checkpoint.metadata?.agent_logs || [],
        checkpointName: checkpoint.name,
        projectId: targetProjectId,
        timestamp: Date.now(),
      };
      sessionStorage.setItem("checkpoint_restore", JSON.stringify(restoreData));
      console.log("[Checkpoint] Stored restore data in sessionStorage");

      // 3. Reload the page to fully reinitialize everything
      console.log("[Checkpoint] Reloading page...");
      window.location.reload();

    } catch (e) {
      console.error("[Checkpoint] Failed to restore:", e);
      alert(`Failed to restore checkpoint: ${e instanceof Error ? e.message : "Unknown error"}`);
      setIsRestoring(false);
      setRestoreDialogOpen(false);
      setRestoreDialogData(null);
    }
  }, [restoreDialogData, state]);

  // Handle resizing
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  // Restore conversation from sessionStorage after page reload (checkpoint restore flow)
  useEffect(() => {
    const restoreDataStr = sessionStorage.getItem("checkpoint_restore");
    if (!restoreDataStr) return;

    try {
      const restoreData = JSON.parse(restoreDataStr);

      // Check if data is fresh (within last 30 seconds - to handle page reload timing)
      const age = Date.now() - (restoreData.timestamp || 0);
      if (age > 30000) {
        console.log("[Checkpoint] Restore data is stale, ignoring");
        sessionStorage.removeItem("checkpoint_restore");
        return;
      }

      console.log("[Checkpoint] Found restore data in sessionStorage");
      console.log("[Checkpoint] Restoring checkpoint:", restoreData.checkpointName);
      console.log("[Checkpoint] Messages:", restoreData.conversation?.length || 0);
      console.log("[Checkpoint] Agent logs:", restoreData.agentLogs?.length || 0);

      // Restore conversation messages
      if (restoreData.conversation && restoreData.conversation.length > 0) {
        const restoredMessages: ChatMessage[] = restoreData.conversation.map(
          (msg: {
            id?: string;
            role: string;
            content: string;
            timestamp?: number;
            toolCalls?: ToolCall[];
            contentBlocks?: ContentBlock[];
            isThinking?: boolean;
            images?: string[];
          }, index: number) => ({
            id: msg.id || `restored-${index}-${Date.now()}`,
            role: msg.role as "user" | "assistant",
            content: msg.content,
            timestamp: msg.timestamp || Date.now(),
            toolCalls: msg.toolCalls || [],
            contentBlocks: msg.contentBlocks || [],
            isThinking: msg.isThinking || false,
            images: msg.images,
          })
        );
        setMessages(restoredMessages);
      }

      // Restore agent logs
      if (restoreData.agentLogs && restoreData.agentLogs.length > 0) {
        restoreAgentLogs(restoreData.agentLogs);
      }

      // Set checkpoint project ID if provided
      if (restoreData.projectId) {
        setCheckpointProjectId(restoreData.projectId);
      }

      // Show checkpoint panel to indicate successful restore
      setShowCheckpointPanel(true);

      // Add a notice to agent logs
      addAgentLog({
        type: "info",
        content: `✓ Restored checkpoint: "${restoreData.checkpointName}"`,
        timestamp: Date.now(),
      });

      // Clear sessionStorage after restore
      sessionStorage.removeItem("checkpoint_restore");
      console.log("[Checkpoint] Restore from sessionStorage complete");

    } catch (e) {
      console.error("[Checkpoint] Failed to restore from sessionStorage:", e);
      sessionStorage.removeItem("checkpoint_restore");
    }
  }, []); // Run once on mount

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing || !containerRef.current) return;
      const containerRect = containerRef.current.getBoundingClientRect();
      // Calculate width relative to main content area (after sidebar)
      const sidebarWidth = 56; // collapsed sidebar width
      const newWidth = e.clientX - containerRect.left;
      setChatPanelWidth(Math.max(280, Math.min(600, newWidth)));
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
  }, [isResizing]);

  // Auto-clone flow: fetch source from URL param and trigger auto-send
  useEffect(() => {
    if (!sourceIdParam || autoCloneTriggered || !isInitialized) return;

    const loadSourceAndTriggerClone = async () => {
      try {
        console.log("[AutoClone] Loading source:", sourceIdParam);
        const result = await getSource(sourceIdParam);

        if (result.success && result.source) {
          const source = result.source;
          // Auto-select the source
          setSelectedSource({
            id: source.id,
            title: source.page_title || "Untitled",
            url: source.source_url,
            theme: themeParam || source.metadata?.theme || "light",
          });

          // Create checkpoint project for this source (CRITICAL: was missing!)
          await ensureCheckpointProject(
            source.id,
            source.page_title || "Untitled",
            source.source_url
          );

          // Open source panel to show selection
          setShowSourcePanel(true);

          // If autoClone is true, trigger auto-send after source is selected
          if (autoCloneParam) {
            console.log("[AutoClone] Will auto-send message");
            // Small delay to ensure source is set before sending
            setTimeout(() => {
              setShouldAutoSend(true);
            }, 500);
          }
        } else {
          console.error("[AutoClone] Failed to load source:", result.error);
        }
      } catch (err) {
        console.error("[AutoClone] Error loading source:", err);
      }

      setAutoCloneTriggered(true);
    };

    loadSourceAndTriggerClone();
  }, [sourceIdParam, themeParam, autoCloneParam, autoCloneTriggered, isInitialized, ensureCheckpointProject]);

  // Auto-restore checkpoint flow: when checkpoint and project params are present
  // Uses the same approach as performRestore - store data in sessionStorage and reload
  useEffect(() => {
    if (!checkpointParam || !projectParam || autoRestoreTriggered || !isInitialized || !state?.sandbox_id) return;

    const triggerAutoRestore = async () => {
      console.log("[AutoRestore] Starting checkpoint restore from URL params");
      console.log("[AutoRestore] Project:", projectParam);
      console.log("[AutoRestore] Checkpoint:", checkpointParam);

      // Mark as triggered immediately to prevent double execution
      setAutoRestoreTriggered(true);

      try {
        const API_BASE = process.env.NEXT_PUBLIC_BOXLITE_API_URL || "http://localhost:5100";
        const sandboxId = state.sandbox_id;

        // 1. Call backend restore API (writes files to sandbox, restarts dev server)
        const response = await fetch(
          `${API_BASE}/api/boxlite/sandbox/${sandboxId}/restore`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_id: projectParam,
              checkpoint_id: checkpointParam,
            }),
          }
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Backend restore failed: ${response.status} ${errorText}`);
        }

        const data = await response.json();
        if (!data.success) {
          throw new Error("Backend restore returned failure");
        }

        console.log("[AutoRestore] Backend restore successful:", data.message);
        const checkpoint = data.checkpoint;

        // 2. Store conversation + metadata in sessionStorage for post-reload restore
        const restoreData = {
          conversation: checkpoint.conversation || [],
          agentLogs: checkpoint.metadata?.agent_logs || [],
          checkpointName: checkpoint.name,
          projectId: projectParam,
          timestamp: Date.now(),
        };
        sessionStorage.setItem("checkpoint_restore", JSON.stringify(restoreData));
        console.log("[AutoRestore] Stored restore data in sessionStorage");

        // 3. Reload the page without URL params to prevent infinite loop
        // Remove checkpoint params from URL before reload
        const newUrl = new URL(window.location.href);
        newUrl.searchParams.delete("checkpoint");
        newUrl.searchParams.delete("project");
        console.log("[AutoRestore] Reloading page to:", newUrl.pathname);
        window.location.href = newUrl.toString();

      } catch (e) {
        console.error("[AutoRestore] Failed to restore:", e);
        addAgentLog({
          type: "error",
          content: `Failed to restore demo: ${e instanceof Error ? e.message : "Unknown error"}`,
          timestamp: Date.now(),
        });
      }
    };

    triggerAutoRestore();
  }, [checkpointParam, projectParam, autoRestoreTriggered, isInitialized, state, addAgentLog]);

  // Show loading state
  if (!isInitialized) {
    return (
      <div className="flex h-screen bg-white dark:bg-neutral-900">
        <AppSidebar currentPage="agent" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center text-neutral-900 dark:text-white">
            <RefreshCw className="h-12 w-12 animate-spin mx-auto mb-4 text-violet-500" />
            <p className="text-lg font-medium">Initializing Nexting Agent...</p>
            {error && <p className="text-red-500 mt-2">{error}</p>}
          </div>
        </div>
      </div>
    );
  }

  // Map BoxLite status to ProjectHeader status
  const getStatus = () => {
    if (!isConnected) return "idle";
    if (state?.status === "ready") return "ready";
    if (state?.status === "error") return "error";
    return "booting";
  };

  return (
    <div className="flex h-screen bg-white dark:bg-neutral-900">
      {/* Navigation Sidebar */}
      <AppSidebar currentPage="agent" />

      {/* Main Content */}
      <main className="flex-1 overflow-hidden flex flex-col min-w-0">
        {/* Project Header */}
        <ProjectHeader
          projectName={projectName}
          showChatPanel={showChatPanel}
          onToggleChatPanel={() => setShowChatPanel(!showChatPanel)}
          showSourcePanel={showSourcePanel}
          onToggleSourcePanel={() => setShowSourcePanel(!showSourcePanel)}
          showCheckpointPanel={showCheckpointPanel}
          onToggleCheckpointPanel={() => setShowCheckpointPanel(!showCheckpointPanel)}
          status={getStatus()}
        />

        {/* Content Area */}
        <div ref={containerRef} className="flex-1 flex overflow-hidden min-h-0">
          {/* AI Chat Panel (Left) */}
          <div
            className="flex-shrink-0 overflow-hidden"
            style={{
              width: `${chatPanelWidth}px`,
              display: showChatPanel ? "block" : "none",
            }}
          >
            {state?.sandbox_id ? (
              <NextingAgentChatPanel
                mode="boxlite"
                sandboxId={state.sandbox_id}
                boxliteState={state}
                onBoxLiteStateUpdate={handleBoxLiteStateUpdate}
                messages={messages}
                onMessagesChange={setMessages}
                onClearFileDiffs={handleClearFileDiffs}
                selectedSource={selectedSource}
                onClearSource={() => setSelectedSource(null)}
                onLoadingChange={setIsAgentLoading}
                onProjectNameGenerated={setProjectName}
                shouldAutoSend={shouldAutoSend}
                onAutoSendComplete={() => setShouldAutoSend(false)}
                onTriggerCheckpointSave={handleSaveCheckpoint}
              />
            ) : (
              <div className="h-full flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 text-neutral-500">
                <div className="text-center">
                  <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-2" />
                  <p>Connecting to sandbox...</p>
                </div>
              </div>
            )}
          </div>

          {/* Resizable Divider */}
          <div
            className={cn(
              "flex-shrink-0 cursor-col-resize relative group",
              "transition-all duration-150",
              "w-px bg-neutral-200 dark:bg-neutral-700",
              "hover:w-1 hover:bg-violet-500 dark:hover:bg-violet-500",
              isResizing && "w-1 bg-violet-500 dark:bg-violet-500"
            )}
            style={{ display: showChatPanel ? "block" : "none" }}
            onMouseDown={handleMouseDown}
          >
            <div
              className={cn(
                "absolute inset-y-0 -left-1 -right-1",
                "group-hover:bg-violet-500/10",
                isResizing && "bg-violet-500/10"
              )}
            />
          </div>

          {/* IDE Panel (Center) */}
          <div className="flex-1 overflow-hidden min-w-0">
            <BoxLiteIDE
              state={state}
              isConnected={isConnected}
              agentLogs={agentLogs}
              fileDiffs={fileDiffs}
              onFileSelect={handleFileSelect}
              onFileCreate={handleFileCreate}
              onFileDelete={handleFileDelete}
              onDiffClear={clearFileDiff}
              onWriteFile={writeFile}
              onTerminalInput={handleTerminalInput}
              getTerminalOutput={getTerminalOutput}
              selectedFile={selectedFile}
              fileContent={fileContent}
              onContentChange={setFileContent}
              onSaveFile={handleSaveFile}
              isResizing={isResizing}
              selectedSource={selectedSource}
            />
          </div>

          {/* Source Panel (Right) */}
          {showSourcePanel && (
            <>
              {/* Divider */}
              <div
                className={cn(
                  "flex-shrink-0 w-px",
                  "bg-neutral-200 dark:bg-neutral-700"
                )}
              />
              <div className="flex-shrink-0 w-72 overflow-hidden">
                <SourcePanel
                  selectedSourceId={selectedSource?.id}
                  disabled={isAgentLoading}
                  onSelectSource={handleSelectSource}
                />
              </div>
            </>
          )}

          {/* Checkpoint Panel (Right) */}
          {showCheckpointPanel && (
            <>
              {/* Divider */}
              <div
                className={cn(
                  "flex-shrink-0 w-px",
                  "bg-neutral-200 dark:bg-neutral-700"
                )}
              />
              <div className="flex-shrink-0 w-72 overflow-hidden">
                <CheckpointPanel
                  projectId={checkpointProjectId}
                  onSaveCheckpoint={handleSaveCheckpoint}
                  onRestoreCheckpoint={handleRestoreCheckpoint}
                  disabled={isAgentLoading}
                />
              </div>
            </>
          )}
        </div>
      </main>

      {/* Restore Checkpoint Confirmation Dialog */}
      <ConfirmDialog
        isOpen={restoreDialogOpen}
        onClose={() => {
          setRestoreDialogOpen(false);
          setRestoreDialogData(null);
        }}
        onConfirm={performRestore}
        title="Restore Checkpoint?"
        description="This will refresh the page and restore all files, conversation history, and logs to the selected checkpoint. Any unsaved changes will be lost."
        confirmText="Restore"
        cancelText="Cancel"
        variant="warning"
        isLoading={isRestoring}
      />
    </div>
  );
}

export default BoxLiteAgentPage;
