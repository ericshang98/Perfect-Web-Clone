/**
 * Showcase API
 *
 * Load showcase data from public directory (static files).
 */

import type {
  ShowcaseMeta,
  ShowcaseReplay,
  ShowcaseFiles,
  Showcase,
} from '@/types/showcase'

const SHOWCASES_BASE_PATH = '/showcases'

/**
 * Load the showcase index (list of all showcases)
 */
export async function loadShowcaseIndex(): Promise<ShowcaseMeta[]> {
  try {
    const response = await fetch(`${SHOWCASES_BASE_PATH}/index.json`)
    if (!response.ok) {
      console.error('Failed to load showcase index:', response.status)
      return []
    }
    const data = await response.json()
    return data.showcases || []
  } catch (error) {
    console.error('Error loading showcase index:', error)
    return []
  }
}

/**
 * Load a single showcase's metadata
 */
export async function loadShowcaseMeta(showcaseId: string): Promise<ShowcaseMeta | null> {
  try {
    const response = await fetch(`${SHOWCASES_BASE_PATH}/${showcaseId}/meta.json`)
    if (!response.ok) {
      console.error(`Failed to load showcase meta for ${showcaseId}:`, response.status)
      return null
    }
    return await response.json()
  } catch (error) {
    console.error(`Error loading showcase meta for ${showcaseId}:`, error)
    return null
  }
}

/**
 * Load a showcase's replay data
 */
export async function loadShowcaseReplay(showcaseId: string): Promise<ShowcaseReplay | null> {
  try {
    const response = await fetch(`${SHOWCASES_BASE_PATH}/${showcaseId}/replay.json`)
    if (!response.ok) {
      console.error(`Failed to load showcase replay for ${showcaseId}:`, response.status)
      return null
    }
    return await response.json()
  } catch (error) {
    console.error(`Error loading showcase replay for ${showcaseId}:`, error)
    return null
  }
}

/**
 * Load a showcase's files
 */
export async function loadShowcaseFiles(showcaseId: string): Promise<ShowcaseFiles | null> {
  try {
    const response = await fetch(`${SHOWCASES_BASE_PATH}/${showcaseId}/files.json`)
    if (!response.ok) {
      console.error(`Failed to load showcase files for ${showcaseId}:`, response.status)
      return null
    }
    return await response.json()
  } catch (error) {
    console.error(`Error loading showcase files for ${showcaseId}:`, error)
    return null
  }
}

/**
 * Load a complete showcase (meta + replay + files)
 */
export async function loadShowcase(showcaseId: string): Promise<Showcase | null> {
  try {
    const [meta, replay, files] = await Promise.all([
      loadShowcaseMeta(showcaseId),
      loadShowcaseReplay(showcaseId),
      loadShowcaseFiles(showcaseId),
    ])

    if (!meta || !replay || !files) {
      console.error(`Incomplete showcase data for ${showcaseId}`)
      return null
    }

    return { meta, replay, files }
  } catch (error) {
    console.error(`Error loading showcase ${showcaseId}:`, error)
    return null
  }
}

/**
 * Check if showcases are available
 */
export async function hasShowcases(): Promise<boolean> {
  const showcases = await loadShowcaseIndex()
  return showcases.length > 0
}
