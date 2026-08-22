# Dockerfile — host the cloned static `dist/` with nginx.
#
# Perfect Web Clone v3 produces a Vite + React + Tailwind project whose
# `npm run build` emits a fully static bundle into `dist/`. This image is the
# OPTIONAL container delivery form of that bundle (the design's "默认交付物:
# dist/ 静态产物 + 可选 Dockerfile(nginx 托管)").
#
# It is a two-stage build:
#   1. `build` — install deps and run the Vite build inside Node, producing
#      /app/dist (the deploy-grade static bundle).
#   2. runtime — copy ONLY that static `dist/` into a tiny nginx image. No Node,
#      no source, no node_modules ship in the final image.
#
# Build context = the assembled project root (the directory that holds
# package.json / vite.config.js / src/ — i.e. a sandbox project assembled by
# `assemble_project` + `build_project`). Build & run:
#
#   docker build -t pwc3-clone .
#   docker run --rm -p 8080:80 pwc3-clone
#   # open http://localhost:8080
#
# Nothing here calls an LLM; this is pure, deterministic delivery packaging.

# ---- Stage 1: build the static bundle -------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first for better layer caching. Copy the lockfile if it
# exists (npm ci) and fall back to npm install otherwise.
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy the rest of the assembled project and produce the static dist/.
COPY . .
RUN npm run build

# ---- Stage 2: serve dist/ with nginx --------------------------------------
FROM nginx:1.27-alpine AS runtime

# SPA-friendly config: serve static files, fall back to index.html so the
# single cloned route resolves regardless of request path.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Ship only the built static bundle.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine's default CMD already runs nginx in the foreground; keep it
# explicit so the intent is obvious.
CMD ["nginx", "-g", "daemon off;"]
