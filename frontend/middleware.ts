import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const response = NextResponse.next();
  const pathname = request.nextUrl.pathname;

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
