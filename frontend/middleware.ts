// AI Traffic Tracking Middleware for Next.js
// Detects AI bot crawlers and AI-referred visitors (non-blocking, observe-only)

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const AI_AGENT_PATTERNS = [
  { pattern: /GPTBot/i, type: 'gptbot' },
  { pattern: /ChatGPT-User/i, type: 'chatgpt-user' },
  { pattern: /ClaudeBot/i, type: 'claudebot' },
  { pattern: /Claude-Web/i, type: 'claudebot' },
  { pattern: /anthropic-ai/i, type: 'anthropic-ai' },
  { pattern: /PerplexityBot/i, type: 'perplexitybot' },
  { pattern: /Google-Extended/i, type: 'google-extended' },
  { pattern: /Googlebot.*AI/i, type: 'google-extended' },
  { pattern: /bingbot/i, type: 'bingbot' },
  { pattern: /cohere-ai/i, type: 'cohere-ai' },
  { pattern: /meta-externalagent/i, type: 'meta-externalagent' },
  { pattern: /FacebookBot/i, type: 'meta-externalagent' },
  { pattern: /Bytespider/i, type: 'bytespider' },
  { pattern: /Applebot.*extended/i, type: 'applebot-extended' },
];

const AI_REFERRAL_PATTERNS = [
  { pattern: /chat\.openai\.com/i, source: 'chatgpt' },
  { pattern: /chatgpt\.com/i, source: 'chatgpt' },
  { pattern: /claude\.ai/i, source: 'claude' },
  { pattern: /perplexity\.ai/i, source: 'perplexity' },
  { pattern: /gemini\.google\.com/i, source: 'gemini' },
  { pattern: /bard\.google\.com/i, source: 'gemini' },
  { pattern: /bing\.com.*chat/i, source: 'bing-copilot' },
  { pattern: /copilot\.microsoft\.com/i, source: 'bing-copilot' },
  { pattern: /you\.com/i, source: 'you-com' },
  { pattern: /phind\.com/i, source: 'phind' },
];

const NEXTING_API_KEY = 'f1b196f85660';
const NEXTING_API_ENDPOINT = 'https://auto-web-two.vercel.app/api/v1/events';

// Send a single event to Nexting
function sendEvent(event: Record<string, unknown>) {
  fetch(NEXTING_API_ENDPOINT, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${NEXTING_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(event),
  }).catch(() => {}); // Silent fail — never block requests
}

// Buffer AI events and send in batches
let eventBuffer: Array<Record<string, unknown>> = [];
let flushTimeout: ReturnType<typeof setTimeout> | null = null;

function flushEvents() {
  if (eventBuffer.length === 0) return;
  const events = [...eventBuffer];
  eventBuffer = [];
  flushTimeout = null;

  fetch(NEXTING_API_ENDPOINT, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${NEXTING_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(events),
  }).catch(() => {}); // Silent fail — never block requests
}

function queueEvent(event: Record<string, unknown>) {
  eventBuffer.push(event);
  if (eventBuffer.length >= 10) {
    flushEvents();
  } else if (!flushTimeout) {
    flushTimeout = setTimeout(flushEvents, 5000);
  }
}

// Send a one-time ping on first request to confirm middleware is connected
let hasSentPing = false;

export function middleware(request: NextRequest) {
  // Send connection ping on first request (confirms middleware is installed)
  if (!hasSentPing) {
    hasSentPing = true;
    sendEvent({
      event_type: 'middleware_ping',
      source: 'middleware',
      url_path: '/__ping__',
      timestamp: new Date().toISOString(),
    });
  }

  const ua = request.headers.get('user-agent') || '';
  const referrer = request.headers.get('referer') || '';
  const url = request.nextUrl;
  const pathname = url.pathname;

  // --- AI Traffic Tracking (non-blocking, observe-only) ---
  let aiAgentType: string | null = null;
  for (const { pattern, type } of AI_AGENT_PATTERNS) {
    if (pattern.test(ua)) {
      aiAgentType = type;
      break;
    }
  }

  let aiReferralSource: string | null = null;
  if (referrer) {
    for (const { pattern, source } of AI_REFERRAL_PATTERNS) {
      if (pattern.test(referrer)) {
        aiReferralSource = source;
        break;
      }
    }
  }

  if (aiAgentType || aiReferralSource) {
    queueEvent({
      event_type: aiAgentType ? 'ai_crawl' : 'ai_referral',
      source: 'middleware',
      ai_agent_type: aiAgentType,
      ai_referral_source: aiReferralSource,
      url_path: pathname,
      user_agent: ua,
      referrer: referrer || undefined,
      utm_source: url.searchParams.get('utm_source') || undefined,
      utm_medium: url.searchParams.get('utm_medium') || undefined,
      utm_campaign: url.searchParams.get('utm_campaign') || undefined,
      timestamp: new Date().toISOString(),
    });
  }

  // --- Existing CORS/COEP headers ---
  const response = NextResponse.next();

  // BoxLite pages - NO COEP (allows iframe to load localhost)
  if (pathname.startsWith('/boxlite')) {
    response.headers.set('Cross-Origin-Opener-Policy', 'same-origin');
    // Explicitly NOT setting COEP for boxlite pages
    return response;
  }

  // All other pages - with COEP for WebContainer support
  response.headers.set('Cross-Origin-Opener-Policy', 'same-origin');
  response.headers.set('Cross-Origin-Embedder-Policy', 'require-corp');

  return response;
}

export const config = {
  matcher: [
    // Match all paths except static files and api routes
    '/((?!_next/static|_next/image|favicon.ico|api).*)',
  ],
};
