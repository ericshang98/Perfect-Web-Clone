'use client'

/**
 * Showcase Gallery Component
 *
 * Displays a grid of pre-recorded agent sessions (showcases).
 * Users can click to watch the replay or import the project.
 */

import React from 'react'
import Image from 'next/image'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Play,
  Download,
  ExternalLink,
  Clock,
  FileCode,
  Layers,
} from 'lucide-react'
import type { ShowcaseMeta } from '@/types/showcase'

// ============================================
// Showcase Card
// ============================================

interface ShowcaseCardProps {
  showcase: ShowcaseMeta
  onWatch: () => void
  onImport: () => void
}

function ShowcaseCard({ showcase, onWatch, onImport }: ShowcaseCardProps) {
  return (
    <Card className="group overflow-hidden hover:shadow-lg transition-all duration-300 border-muted">
      {/* Preview Image */}
      <div className="relative aspect-video bg-muted overflow-hidden">
        {showcase.preview_image ? (
          <Image
            src={showcase.preview_image}
            alt={showcase.name}
            fill
            className="object-cover object-top group-hover:scale-105 transition-transform duration-500"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <FileCode className="h-12 w-12" />
          </div>
        )}

        {/* Hover Overlay */}
        <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center gap-3">
          <Button
            size="sm"
            variant="secondary"
            className="gap-2"
            onClick={(e) => {
              e.stopPropagation()
              onWatch()
            }}
          >
            <Play className="h-4 w-4" />
            Watch
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="gap-2 bg-white/10 hover:bg-white/20 border-white/20"
            onClick={(e) => {
              e.stopPropagation()
              onImport()
            }}
          >
            <Download className="h-4 w-4" />
            Import
          </Button>
        </div>

        {/* Source Badge */}
        <a
          href={showcase.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={(e) => e.stopPropagation()}
        >
          <Badge variant="secondary" className="gap-1 bg-white/90">
            <ExternalLink className="h-3 w-3" />
            Source
          </Badge>
        </a>
      </div>

      {/* Content */}
      <CardContent className="p-4">
        <h3 className="font-semibold text-lg mb-1 group-hover:text-primary transition-colors">
          {showcase.name}
        </h3>
        <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
          {showcase.description}
        </p>

        {/* Stats */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Layers className="h-3.5 w-3.5" />
            {showcase.stats.sections} sections
          </span>
          <span className="flex items-center gap-1">
            <FileCode className="h-3.5 w-3.5" />
            {showcase.stats.files} files
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {showcase.stats.duration_seconds}s
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

// ============================================
// Showcase Gallery
// ============================================

interface ShowcaseGalleryProps {
  showcases: ShowcaseMeta[]
  onWatch: (showcaseId: string) => void
  onImport: (showcaseId: string) => void
  title?: string
  description?: string
}

export function ShowcaseGallery({
  showcases,
  onWatch,
  onImport,
  title = "Community Clones",
  description = "See what others have built with Perfect Web Clone. Click any card to explore.",
}: ShowcaseGalleryProps) {
  if (showcases.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <FileCode className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No showcases available yet.</p>
      </div>
    )
  }

  return (
    <section className="py-12">
      {/* Header */}
      <div className="text-center mb-10">
        <Badge variant="outline" className="mb-4">
          GALLERY
        </Badge>
        <h2 className="text-3xl font-bold tracking-tight mb-3">
          {title}
        </h2>
        <p className="text-muted-foreground max-w-2xl mx-auto">
          {description}
        </p>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {showcases.map((showcase) => (
          <ShowcaseCard
            key={showcase.id}
            showcase={showcase}
            onWatch={() => onWatch(showcase.id)}
            onImport={() => onImport(showcase.id)}
          />
        ))}
      </div>
    </section>
  )
}

// ============================================
// Showcase Loading State
// ============================================

export function ShowcaseGallerySkeleton() {
  return (
    <section className="py-12">
      <div className="text-center mb-10">
        <div className="h-6 w-20 bg-muted rounded mx-auto mb-4 animate-pulse" />
        <div className="h-9 w-64 bg-muted rounded mx-auto mb-3 animate-pulse" />
        <div className="h-5 w-96 bg-muted rounded mx-auto animate-pulse" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <Card key={i} className="overflow-hidden">
            <div className="aspect-video bg-muted animate-pulse" />
            <CardContent className="p-4">
              <div className="h-6 w-3/4 bg-muted rounded mb-2 animate-pulse" />
              <div className="h-4 w-full bg-muted rounded mb-1 animate-pulse" />
              <div className="h-4 w-2/3 bg-muted rounded mb-3 animate-pulse" />
              <div className="flex gap-4">
                <div className="h-4 w-20 bg-muted rounded animate-pulse" />
                <div className="h-4 w-16 bg-muted rounded animate-pulse" />
                <div className="h-4 w-12 bg-muted rounded animate-pulse" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  )
}

export default ShowcaseGallery
