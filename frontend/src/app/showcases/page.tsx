'use client'

/**
 * Showcases Page
 *
 * Displays all community clones with replay functionality.
 * Users can watch recorded agent sessions and import projects.
 */

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Header } from '@/components/landing'
import { ShowcaseGallery, ShowcaseGallerySkeleton } from '@/components/showcase/showcase-gallery'
import { ReplayViewer } from '@/components/showcase/replay-viewer'
import { loadShowcaseIndex, loadShowcase } from '@/lib/api/showcases'
import type { ShowcaseMeta, Showcase } from '@/types/showcase'
import { Header as HeaderType } from '@/types/landing'

// Header config (same as homepage)
const headerConfig: HeaderType = {
  id: 'header',
  brand: {
    title: '',
    logo: { src: '/logo.svg', alt: 'Nexting', width: 180, height: 48 },
    url: '/',
  },
  nav: {
    items: [
      {
        title: 'Tools',
        icon: 'Wrench',
        children: [
          { title: 'Web Extractor', description: 'Extract webpage structure', url: '/extractor', icon: 'Globe' },
          { title: 'Clone Agent', description: 'AI-powered generation', url: '/agent', icon: 'Bot' },
        ],
      },
      { title: 'About', url: '/about', icon: 'User' },
      { title: 'Docs', url: '/docs', icon: 'BookOpenText' },
      { title: 'GitHub', url: 'https://github.com/ericshang98', target: '_blank', icon: 'Github' },
    ],
  },
  buttons: [],
  user_nav: {
    show_name: true,
    show_credits: false,
    show_sign_out: true,
    items: [{ title: 'Settings', url: '/settings/profile', icon: 'Settings' }],
  },
  show_sign: true,
  show_theme: true,
  show_locale: false,
}

export default function ShowcasesPage() {
  const router = useRouter()
  const [showcases, setShowcases] = useState<ShowcaseMeta[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedShowcase, setSelectedShowcase] = useState<Showcase | null>(null)
  const [isViewerOpen, setIsViewerOpen] = useState(false)

  // Load showcase index on mount
  useEffect(() => {
    async function load() {
      setIsLoading(true)
      const data = await loadShowcaseIndex()
      setShowcases(data)
      setIsLoading(false)
    }
    load()
  }, [])

  // Handle watch - load full showcase and open viewer
  const handleWatch = async (showcaseId: string) => {
    const showcase = await loadShowcase(showcaseId)
    if (showcase) {
      setSelectedShowcase(showcase)
      setIsViewerOpen(true)
    }
  }

  // Handle import - navigate to agent page with showcase files
  const handleImport = async (showcaseId: string) => {
    // For now, just navigate to agent page
    // TODO: Implement actual import functionality
    router.push(`/agent?import=${showcaseId}`)
  }

  // Close viewer
  const handleCloseViewer = () => {
    setIsViewerOpen(false)
    setSelectedShowcase(null)
  }

  return (
    <main className="min-h-screen bg-background">
      <Header header={headerConfig} />

      <div className="container py-12">
        {isLoading ? (
          <ShowcaseGallerySkeleton />
        ) : isViewerOpen && selectedShowcase ? (
          <div className="h-[calc(100vh-200px)] rounded-lg border bg-card overflow-hidden">
            <ReplayViewer
              showcase={selectedShowcase.meta}
              replay={selectedShowcase.replay}
              files={selectedShowcase.files}
              onImport={() => handleImport(selectedShowcase.meta.id)}
              onClose={handleCloseViewer}
            />
          </div>
        ) : (
          <ShowcaseGallery
            showcases={showcases}
            onWatch={handleWatch}
            onImport={handleImport}
            title="Community Clones"
            description="Watch how the AI agent builds these projects step by step. Click Watch to see the replay or Import to start editing."
          />
        )}
      </div>
    </main>
  )
}
