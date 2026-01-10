/**
 * Replay Player Hook
 *
 * Plays back recorded agent sessions for the Gallery showcase.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import type {
  ShowcaseReplay,
  ShowcaseFiles,
  ReplayEvent,
  ReplayPlayerState,
  ReplayMessage,
  WorkerStatus,
} from '@/types/showcase'

interface UseReplayPlayerOptions {
  /** Playback speed multiplier (default: 2) */
  defaultSpeed?: number
  /** Maximum delay between events in ms (default: 2000) */
  maxDelay?: number
  /** Auto-start playback (default: true) */
  autoPlay?: boolean
  /** Callback when playback completes */
  onComplete?: () => void
  /** Callback when file is "written" */
  onFileWritten?: (path: string, content: string) => void
}

interface UseReplayPlayerReturn extends ReplayPlayerState {
  // Controls
  play: () => void
  pause: () => void
  resume: () => void
  skip: () => void
  restart: () => void
  setSpeed: (speed: number) => void
  seekTo: (eventIndex: number) => void
}

export function useReplayPlayer(
  replay: ShowcaseReplay | null,
  files: ShowcaseFiles | null,
  options: UseReplayPlayerOptions = {}
): UseReplayPlayerReturn {
  const {
    defaultSpeed = 2,
    maxDelay = 2000,
    autoPlay = true,
    onComplete,
    onFileWritten,
  } = options

  // State
  const [isPlaying, setIsPlaying] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [currentEventIndex, setCurrentEventIndex] = useState(0)
  const [elapsedTime, setElapsedTime] = useState(0)
  const [playbackSpeed, setPlaybackSpeed] = useState(defaultSpeed)

  // Display state
  const [messages, setMessages] = useState<ReplayMessage[]>([])
  const [currentFiles, setCurrentFiles] = useState<Record<string, string>>({})
  const [workerStatuses, setWorkerStatuses] = useState<Record<string, WorkerStatus>>({})

  // Refs
  const timerRef = useRef<NodeJS.Timeout | null>(null)
  const messageIdRef = useRef(0)

  // Derived values
  const totalEvents = replay?.events.length ?? 0
  const progress = totalEvents > 0 ? currentEventIndex / totalEvents : 0
  const currentEvent = replay?.events[currentEventIndex] ?? null

  // Clear timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [])

  // Auto-play on mount
  useEffect(() => {
    if (replay && autoPlay && !isPlaying && !isComplete) {
      play()
    }
  }, [replay])

  // ============================================
  // Event Processing
  // ============================================

  const processEvent = useCallback((event: ReplayEvent) => {
    const messageId = `msg-${messageIdRef.current++}`

    switch (event.type) {
      case 'agent_thinking':
        setMessages(prev => [...prev, {
          id: messageId,
          type: 'agent',
          content: event.content,
          timestamp: event.timestamp,
        }])
        break

      case 'tool_call':
        setMessages(prev => [...prev, {
          id: messageId,
          type: 'tool',
          content: `Calling ${event.tool_name}...`,
          timestamp: event.timestamp,
          toolName: event.tool_name,
        }])
        break

      case 'tool_result':
        // Update last tool message with result
        setMessages(prev => {
          const lastToolIndex = prev.findLastIndex(m => m.toolName === event.tool_name)
          if (lastToolIndex >= 0) {
            const updated = [...prev]
            updated[lastToolIndex] = {
              ...updated[lastToolIndex],
              content: event.success
                ? `${event.tool_name} completed`
                : `${event.tool_name} failed`,
              toolResult: event.result,
            }
            return updated
          }
          return prev
        })
        break

      case 'worker_spawned':
        // Initialize worker statuses
        const newStatuses: Record<string, WorkerStatus> = {}
        for (const worker of event.workers) {
          newStatuses[worker.worker_id] = {
            worker_id: worker.worker_id,
            section_name: worker.section_name,
            display_name: worker.display_name,
            status: 'pending',
            files_written: [],
          }
        }
        setWorkerStatuses(newStatuses)

        setMessages(prev => [...prev, {
          id: messageId,
          type: 'system',
          content: `Spawning ${event.workers.length} workers...`,
          timestamp: event.timestamp,
        }])
        break

      case 'worker_progress':
        setWorkerStatuses(prev => ({
          ...prev,
          [event.worker_id]: {
            ...prev[event.worker_id],
            status: event.status === 'started' ? 'running'
                  : event.status === 'completed' ? 'completed'
                  : event.status === 'failed' ? 'failed'
                  : prev[event.worker_id]?.status ?? 'pending',
            files_written: event.file_path
              ? [...(prev[event.worker_id]?.files_written ?? []), event.file_path]
              : prev[event.worker_id]?.files_written ?? [],
          },
        }))
        break

      case 'file_written':
        setCurrentFiles(prev => ({
          ...prev,
          [event.path]: event.content,
        }))
        onFileWritten?.(event.path, event.content)
        break

      case 'preview_ready':
        setMessages(prev => [...prev, {
          id: messageId,
          type: 'system',
          content: `Preview ready at ${event.url}`,
          timestamp: event.timestamp,
        }])
        break

      case 'error':
        setMessages(prev => [...prev, {
          id: messageId,
          type: 'system',
          content: `Error: ${event.message}`,
          timestamp: event.timestamp,
        }])
        break
    }
  }, [onFileWritten])

  // ============================================
  // Playback Logic
  // ============================================

  const scheduleNextEvent = useCallback(() => {
    if (!replay || currentEventIndex >= replay.events.length) {
      // Playback complete
      setIsPlaying(false)
      setIsComplete(true)
      onComplete?.()
      return
    }

    const currentEvent = replay.events[currentEventIndex]
    const nextEvent = replay.events[currentEventIndex + 1]

    // Process current event
    processEvent(currentEvent)
    setElapsedTime(currentEvent.timestamp)

    // Calculate delay to next event
    let delay = 100 // Default minimum delay
    if (nextEvent) {
      delay = Math.min(
        (nextEvent.timestamp - currentEvent.timestamp) / playbackSpeed,
        maxDelay / playbackSpeed
      )
      delay = Math.max(delay, 50) // Minimum 50ms
    }

    // Schedule next event
    timerRef.current = setTimeout(() => {
      setCurrentEventIndex(prev => prev + 1)
    }, delay)
  }, [replay, currentEventIndex, playbackSpeed, maxDelay, processEvent, onComplete])

  // Run playback
  useEffect(() => {
    if (isPlaying && !isPaused && replay) {
      scheduleNextEvent()
    }
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [isPlaying, isPaused, currentEventIndex, scheduleNextEvent])

  // ============================================
  // Controls
  // ============================================

  const play = useCallback(() => {
    if (!replay) return
    setIsPlaying(true)
    setIsPaused(false)
    setIsComplete(false)
  }, [replay])

  const pause = useCallback(() => {
    setIsPaused(true)
    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }
  }, [])

  const resume = useCallback(() => {
    setIsPaused(false)
  }, [])

  const skip = useCallback(() => {
    // Jump to end state
    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }

    // Load all files
    if (files) {
      setCurrentFiles(files.files)
    }

    // Process all events to get final messages
    if (replay) {
      setMessages([])
      messageIdRef.current = 0

      // Just show summary message
      setMessages([{
        id: 'summary',
        type: 'system',
        content: `Playback skipped. ${Object.keys(files?.files ?? {}).length} files loaded.`,
        timestamp: replay.total_duration_ms,
      }])

      setCurrentEventIndex(replay.events.length)
      setElapsedTime(replay.total_duration_ms)
    }

    setIsPlaying(false)
    setIsComplete(true)
    onComplete?.()
  }, [replay, files, onComplete])

  const restart = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }

    // Reset all state
    setCurrentEventIndex(0)
    setElapsedTime(0)
    setMessages([])
    setCurrentFiles({})
    setWorkerStatuses({})
    setIsComplete(false)
    setIsPaused(false)
    messageIdRef.current = 0

    // Start playing
    setIsPlaying(true)
  }, [])

  const setSpeed = useCallback((speed: number) => {
    setPlaybackSpeed(Math.max(0.5, Math.min(speed, 5)))
  }, [])

  const seekTo = useCallback((eventIndex: number) => {
    if (!replay) return

    // Pause current playback
    if (timerRef.current) {
      clearTimeout(timerRef.current)
    }

    // Reset state
    setMessages([])
    setCurrentFiles({})
    setWorkerStatuses({})
    messageIdRef.current = 0

    // Process all events up to target
    for (let i = 0; i <= eventIndex && i < replay.events.length; i++) {
      processEvent(replay.events[i])
    }

    setCurrentEventIndex(eventIndex)
    setElapsedTime(replay.events[eventIndex]?.timestamp ?? 0)
    setIsComplete(eventIndex >= replay.events.length - 1)
  }, [replay, processEvent])

  return {
    // State
    isPlaying,
    isPaused,
    isComplete,
    currentEventIndex,
    totalEvents,
    progress,
    elapsedTime,
    currentEvent,
    messages,
    files: currentFiles,
    workerStatuses,
    playbackSpeed,

    // Controls
    play,
    pause,
    resume,
    skip,
    restart,
    setSpeed,
    seekTo,
  }
}
