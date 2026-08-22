import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'perfect-web-clone'
export const inject = ['tools']

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_DIR = join(PLUGIN_DIR, '..')
const SKILL_FILE = join(REPO_DIR, 'skill', 'SKILL.md')

function runPwc(args) {
  return new Promise((resolve, reject) => {
    const child = spawn('pwc', args, {
      cwd: REPO_DIR,
      env: process.env,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => {
      stdout += chunk
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk
    })
    child.on('error', (err) => {
      if (err && err.code === 'ENOENT') {
        reject(new Error(
          'pwc CLI not found on PATH. Install the Python package: pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git" && playwright install chromium',
        ))
        return
      }
      reject(err)
    })
    child.on('close', (code) => {
      const text = (stdout || stderr || '').trim()
      if (code !== 0) {
        reject(new Error(text || `pwc ${args.join(' ')} exited ${code}`))
        return
      }
      resolve(text)
    })
  })
}

function parseJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return { ok: false, error: text }
  }
}

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'pwc_extract',
    description: 'Capture a live URL into immutable source evidence. Returns source_id plus capture summary. Never calls an LLM.',
    parameters: {
      url: { type: 'string', required: true, description: 'https URL to clone' },
    },
    async execute(args) {
      return parseJson(await runPwc(['extract', args.url]))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_plan',
    description: 'Deterministic section plan for a captured source_id.',
    parameters: {
      source_id: { type: 'string', required: true, description: 'id returned by pwc_extract' },
    },
    async execute(args) {
      return parseJson(await runPwc(['plan', args.source_id]))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_assemble',
    description: 'Write the Vite + React shell for a source_id. Does not invent section components.',
    parameters: {
      source_id: { type: 'string', required: true, description: 'id returned by pwc_extract' },
    },
    async execute(args) {
      return parseJson(await runPwc(['assemble', args.source_id]))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_build',
    description: 'Run npm run build in the active clone sandbox.',
    parameters: {},
    async execute() {
      return parseJson(await runPwc(['build']))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_fingerprints',
    description: 'Scan a directory for source-framework fingerprints (Shopify class names, original.css, etc.).',
    parameters: {
      dirpath: { type: 'string', required: true, description: 'usually the clone dist/ directory' },
    },
    async execute(args) {
      return parseJson(await runPwc(['fingerprints', args.dirpath]))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_weight',
    description: 'Measure gzipped HTML/CSS/JS weight of a dist tree against a KB budget.',
    parameters: {
      dirpath: { type: 'string', required: true, description: 'clone dist/ directory' },
      budget_kb: { type: 'number', description: 'gzip budget, default 120' },
    },
    async execute(args) {
      const extra = args.budget_kb != null ? ['--budget-kb', String(args.budget_kb)] : []
      return parseJson(await runPwc(['weight', args.dirpath, ...extra]))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'pwc_score',
    description: 'SSIM-score a clone screenshot against the captured reference. Optional per-section bounds JSON.',
    parameters: {
      ref: { type: 'string', required: true, description: 'reference PNG path' },
      cand: { type: 'string', required: true, description: 'clone PNG path' },
      sections: { type: 'string', description: 'optional path to sections JSON' },
    },
    async execute(args) {
      const extra = args.sections ? ['--sections', args.sections] : []
      return parseJson(await runPwc(['score', '--ref', args.ref, '--cand', args.cand, ...extra]))
    },
  }))

  const skills = ctx.get('skills')
  if (skills) {
    skills.register({
      name: 'perfect-web-clone',
      description: 'Clone a live webpage into a measured Vite+React project. Use when the user pastes a URL to clone, copy, reproduce, replicate, or 复刻 a site.',
      content: readFileSync(SKILL_FILE, 'utf8'),
      source: 'runtime',
      provider: 'perfect-web-clone',
    })
  }
}
