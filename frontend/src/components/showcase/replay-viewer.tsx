'use client'

/**
 * Replay Viewer Component
 *
 * Displays a recorded agent session with playback controls.
 * Shows the agent's thinking, tool calls, and file generation in real-time.
 */

import React, { useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import {
  Play,
  Pause,
  SkipForward,
  RotateCcw,
  Gauge,
  Check,
  Loader2,
  AlertCircle,
  FileCode,
  Bot,
  Wrench,
  Info,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useReplayPlayer } from '@/hooks/use-replay-player'
import type {
  ShowcaseReplay,
  ShowcaseFiles,
  ShowcaseMeta,
  ReplayMessage,
  WorkerStatus,
} from '@/types/showcase'

// ============================================
// Message Item
// ============================================

function MessageItem({ message }: { message: ReplayMessage }) {
  const iconMap = {
    agent: <Bot className="h-4 w-4" />,
    tool: <Wrench className="h-4 w-4" />,
    system: <Info className="h-4 w-4" />,
  }

  const colorMap = {
    agent: 'bg-primary/10 text-primary',
    tool: 'bg-blue-500/10 text-blue-500',
    system: 'bg-muted text-muted-foreground',
  }

  return (
    <div className="flex gap-3 py-3">
      <div className={cn(
        "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
        colorMap[message.type]
      )}>
        {iconMap[message.type]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm whitespace-pre-wrap break-words">
          {message.content}
        </div>
        {message.toolResult && (
          <div className="mt-2 p-2 bg-muted rounded text-xs font-mono overflow-auto max-h-32">
            {message.toolResult.slice(0, 500)}
            {message.toolResult.length > 500 && '...'}
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================
// Worker Progress
// ============================================

function WorkerProgressList({ workers }: { workers: Record<string, WorkerStatus> }) {
  const workerList = Object.values(workers)

  if (workerList.length === 0) return null

  const completedCount = workerList.filter(w => w.status === 'completed').length
  const totalCount = workerList.length
  const progress = (completedCount / totalCount) * 100

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">Worker Progress</span>
        <span className="font-medium">{completedCount}/{totalCount}</span>
      </div>
      <Progress value={progress} className="h-2" />
      <div className="grid grid-cols-2 gap-2">
        {workerList.map((worker) => (
          <div
            key={worker.worker_id}
            className={cn(
              "flex items-center gap-2 p-2 rounded text-xs",
              worker.status === 'completed' && "bg-green-500/10 text-green-600",
              worker.status === 'running' && "bg-blue-500/10 text-blue-600",
              worker.status === 'failed' && "bg-red-500/10 text-red-600",
              worker.status === 'pending' && "bg-muted text-muted-foreground",
            )}
          >
            {worker.status === 'completed' && <Check className="h-3 w-3" />}
            {worker.status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
            {worker.status === 'failed' && <AlertCircle className="h-3 w-3" />}
            {worker.status === 'pending' && <div className="h-3 w-3 rounded-full bg-current opacity-30" />}
            <span className="truncate">{worker.display_name || worker.section_name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ============================================
// File List
// ============================================

function FileList({ files }: { files: Record<string, string> }) {
  const fileCount = Object.keys(files).length

  if (fileCount === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-4">
        No files generated yet...
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {Object.keys(files).map((path) => (
        <div
          key={path}
          className="flex items-center gap-2 p-2 hover:bg-muted rounded text-sm"
        >
          <FileCode className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <span className="truncate font-mono text-xs">{path}</span>
          <Badge variant="outline" className="ml-auto text-xs">
            {(files[path].length / 1024).toFixed(1)}KB
          </Badge>
        </div>
      ))}
    </div>
  )
}

// ============================================
// Playback Controls
// ============================================

interface PlaybackControlsProps {
  isPlaying: boolean
  isPaused: boolean
  isComplete: boolean
  progress: number
  elapsedTime: number
  totalDuration: number
  playbackSpeed: number
  onPlay: () => void
  onPause: () => void
  onResume: () => void
  onSkip: () => void
  onRestart: () => void
  onSpeedChange: (speed: number) => void
}

function PlaybackControls({
  isPlaying,
  isPaused,
  isComplete,
  progress,
  elapsedTime,
  totalDuration,
  playbackSpeed,
  onPlay,
  onPause,
  onResume,
  onSkip,
  onRestart,
  onSpeedChange,
}: PlaybackControlsProps) {
  const formatTime = (ms: number) => {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
  }

  return (
    <div className="space-y-3">
      {/* Progress Bar */}
      <div className="space-y-1">
        <Progress value={progress * 100} className="h-1.5" />
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{formatTime(elapsedTime)}</span>
          <span>{formatTime(totalDuration)}</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-2">
        {/* Restart */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onRestart}
          disabled={!isComplete && elapsedTime === 0}
        >
          <RotateCcw className="h-4 w-4" />
        </Button>

        {/* Play/Pause */}
        {isComplete ? (
          <Button size="icon" onClick={onRestart}>
            <RotateCcw className="h-4 w-4" />
          </Button>
        ) : isPaused ? (
          <Button size="icon" onClick={onResume}>
            <Play className="h-4 w-4" />
          </Button>
        ) : isPlaying ? (
          <Button size="icon" onClick={onPause}>
            <Pause className="h-4 w-4" />
          </Button>
        ) : (
          <Button size="icon" onClick={onPlay}>
            <Play className="h-4 w-4" />
          </Button>
        )}

        {/* Skip */}
        <Button
          variant="ghost"
          size="icon"
          onClick={onSkip}
          disabled={isComplete}
        >
          <SkipForward className="h-4 w-4" />
        </Button>

        {/* Speed */}
        <div className="flex items-center gap-1 ml-4">
          <Gauge className="h-4 w-4 text-muted-foreground" />
          <select
            value={playbackSpeed}
            onChange={(e) => onSpeedChange(Number(e.target.value))}
            className="text-sm bg-transparent border-none focus:ring-0 cursor-pointer"
          >
            <option value={1}>1x</option>
            <option value={2}>2x</option>
            <option value={3}>3x</option>
            <option value={5}>5x</option>
          </select>
        </div>
      </div>
    </div>
  )
}

// ============================================
// Main Replay Viewer
// ============================================

interface ReplayViewerProps {
  showcase: ShowcaseMeta
  replay: ShowcaseReplay
  files: ShowcaseFiles
  onImport?: () => void
  onClose?: () => void
}

export function ReplayViewer({
  showcase,
  replay,
  files,
  onImport,
  onClose,
}: ReplayViewerProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const player = useReplayPlayer(replay, files, {
    defaultSpeed: 2,
    autoPlay: true,
  })

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [player.messages])

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-semibold">{showcase.name}</h2>
            <p className="text-sm text-muted-foreground">{showcase.description}</p>
          </div>
          <div className="flex gap-2">
            {player.isComplete && onImport && (
              <Button onClick={onImport} className="gap-2">
                <FileCode className="h-4 w-4" />
                Import Project
              </Button>
            )}
            {onClose && (
              <Button variant="outline" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        </div>

        {/* Playback Controls */}
        <PlaybackControls
          isPlaying={player.isPlaying}
          isPaused={player.isPaused}
          isComplete={player.isComplete}
          progress={player.progress}
          elapsedTime={player.elapsedTime}
          totalDuration={replay.total_duration_ms}
          playbackSpeed={player.playbackSpeed}
          onPlay={player.play}
          onPause={player.pause}
          onResume={player.resume}
          onSkip={player.skip}
          onRestart={player.restart}
          onSpeedChange={player.setSpeed}
        />
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 flex">
        {/* Left: Messages */}
        <div className="flex-1 overflow-auto p-4 border-r">
          <div className="space-y-1">
            {player.messages.map((message) => (
              <MessageItem key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>

          {player.messages.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <Bot className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>Waiting for playback to start...</p>
            </div>
          )}
        </div>

        {/* Right: Workers & Files */}
        <div className="w-80 flex-shrink-0 overflow-auto p-4 space-y-6">
          {/* Workers */}
          <WorkerProgressList workers={player.workerStatuses} />

          <Separator />

          {/* Files */}
          <div>
            <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
              <FileCode className="h-4 w-4" />
              Generated Files
              <Badge variant="secondary" className="ml-auto">
                {Object.keys(player.files).length}
              </Badge>
            </h3>
            <FileList files={player.files} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default ReplayViewer
