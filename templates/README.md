# templates/

Static scaffolding and delivery templates for Perfect Web Clone v3. Everything
here is plain text / config — **no file in this directory calls an LLM**, and
the MCP tools never reason over them; they are deterministic build & delivery
material.

## Contents

| Path | What it is | Used by |
|---|---|---|
| `base-project/` | The base Vite + React + Tailwind project a clone starts from (index.html, package.json, vite/tailwind/postcss config, `src/main.jsx`, placeholder `src/App.jsx`, `src/index.css`, empty `src/components/sections/`). | Sandbox scaffold. **Pre-existing — do not modify here.** |
| `Dockerfile` | Two-stage build: run `npm run build`, then serve the static `dist/` with nginx. The OPTIONAL container delivery form of a clone. | `docker build` over an assembled project root. |
| `nginx.conf` | Static host config copied into the nginx image: serve hashed `/assets`, SPA-fallback to `index.html`. | `Dockerfile` (stage 2). |
| `.dockerignore` | Trims the Docker build context (excludes `node_modules`, `dist`, `.git`, …). | `docker build`. |
| `assembly/App.jsx.template` | **Reference only.** Shows the exact shape of `src/App.jsx` that `assemble_project` emits. | Documentation / human + Claude Code reference. |
| `assembly/index.css.template` | **Reference only.** Shows the exact shape of `src/index.css` that `assemble_project` emits. | Documentation / human + Claude Code reference. |

## On the `assembly/*.template` files

`mcp_server/tools/build_deploy.py::assemble_project` renders `src/App.jsx` and
`src/index.css` **in pure Python** (`_render_app_jsx` / `_render_index_css`) and
writes them straight into the sandbox. It does **not** read these `.template`
files at runtime. They exist so the assembly output contract is documented and
reviewable in one place; if `_render_app_jsx` / `_render_index_css` change, keep
these snippets in sync.

## Docker delivery (optional)

Deployment is not a goal of v3 — these are just the container form of a
deploy-grade `dist/`. From an assembled project root (the dir with
`package.json`, `vite.config.js`, `src/`), copy `Dockerfile`, `nginx.conf` and
`.dockerignore` alongside it, then:

```sh
docker build -t pwc3-clone .
docker run --rm -p 8080:80 pwc3-clone
# open http://localhost:8080
```
