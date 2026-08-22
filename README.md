# Perfect Web Clone

**A pixel-clone agent on DeepSeek Harness. Paste a URL. The gates decide, not the model.**

This repository is the public clone runtime:

- **DeepSeek Harness** runs the conversation, the model, and the tool loop
- **`pwc` core** captures the page, plans sections, assembles a Vite + React shell, and scores the result
- **The skill** tells the agent to repair the worst measured section until the gates are green or the budget is gone

v2 (Claude Agent SDK + FastAPI + Next.js IDE) is archived as the `v2-archive` tag. Do not revive that loop.

## Install

Python 3.10+ and Node 20+ (for DeepSeek Harness and the Vite clone output).

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium

npx @deepseek-ai/dsh web
dsh plugin --profile web add github:ericshang98/Perfect-Web-Clone
```

Then say:

```text
clone https://example.com
```

Claude Code / Codex users can install the same playbook from
[`perfect-web-clone-skill`](https://github.com/ericshang98/perfect-web-clone-skill)
and run the `pwc` CLI locally.

## What actually happens

1. `pwc extract <url>` — Playwright capture, assets localized, integrity checked
2. `pwc plan <source_id>` — deterministic sections from real `#main` children
3. The agent authors clean React for each section
4. `pwc assemble` / `pwc build` — Vite + React + Tailwind shell
5. `pwc fingerprints`, `pwc weight`, `pwc score` — measured gates
6. Repair the worst section, rebuild, re-measure
7. Stop at `ready_for_user_review` or `failed_with_residuals`

The core never calls an LLM. If a page is WebGL, runtime canvas, or
scroll-choreographed, the classifier reports that ceiling up front. Content
still clones; the runtime-drawn look may not.

## CLI

```bash
pwc extract https://example.com
pwc plan <source_id>
pwc assemble <source_id>
pwc build
pwc fingerprints dist/
pwc weight dist/
pwc score --ref reference.png --cand clone.png
```

Every command prints JSON. `ok` is the only pass/fail that matters.

## Layout

```text
core/          deterministic extract / plan / gates / sandbox
pwc/           CLI
plugin/        DeepSeek Harness tools + skill registration
skill/         the playbook (same file published to the skill repo)
templates/     Vite + React + Tailwind shell
```

Private customer sites and the private v4 MCP server are not in this repository.

## License

MIT
