# Nexting

<div align="center">

**AI-Powered Web Cloning Tool - Extract, Analyze, Clone**

English | [中文](./docs/cn/README_CN.md) | [日本語](./docs/ja/README_JA.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

Others guess from screenshots. We extract the **real code** — DOM, styles, components, interactions. Get pixel-perfect, maintainable output in seconds.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Table of Contents

- [Why Nexting?](#why-nexting)
- [Features](#features)
- [Demo](#demo)
- [Getting Started](#getting-started)
- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Tech Stack](#tech-stack)
- [Contributing](#contributing)
- [License](#license)

## Why Nexting?

### Screenshot Tools vs Code Extraction

Most AI cloning tools look at your page like a picture and **guess** the code. We read the **actual source** — that's why our output is production-ready, not a rough approximation.

| Screenshot-Based Tools | Nexting |
|------------------------|---------|
| AI interprets pixels → guesses layout | Extracts real DOM → analyzes CSS |
| Hardcoded pixel values | Responsive with flexible units |
| Dead interactions | Living hover effects & animations |
| Divs all the way down | Semantic HTML preserved |
| Unmaintainable output | Clean, modular components |

## Features

### Web Extractor
- **Full Page Capture** - Extract complete DOM structure, CSS styles, and assets using Playwright
- **Theme Detection** - Automatically detect and capture both light and dark themes
- **Component Analysis** - AI-powered component boundary detection
- **Tech Stack Analysis** - Identify frameworks and libraries used on the page
- **Asset Extraction** - Download images, fonts, and other resources

### Clone Agent
- **Multi-Agent Architecture** - Specialized agents work in parallel for faster, more accurate results
- **AI Code Generation** - Claude generates production-ready code from extracted data
- **Live Preview** - Real-time code preview with WebContainer (StackBlitz)
- **Framework Support** - Export to React, Next.js, Vue, or plain HTML

### Multi-Agent System

Traditional single-model approaches fail on complex pages. Our multi-agent system breaks down the problem:

| Agent | Responsibility |
|-------|----------------|
| **DOM Structure Agent** | Handles massive, deeply nested DOM trees. Extracts semantic structure and component boundaries. |
| **Style Analysis Agent** | Processes thousands of CSS rules. Captures computed styles, CSS variables, and breakpoints. |
| **Component Detection Agent** | Identifies reusable patterns across the codebase for modular output. |
| **Code Generation Agent** | Synthesizes all outputs into production-ready, framework-specific code. |

## Demo

<div align="center">

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

</div>

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### Quick Start

1. **Clone the repository**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Backend Setup**

```bash
cd backend

# Copy environment file and add your API key
cp ../.env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start the server (auto-installs dependencies)
sh start.sh
```

3. **Frontend Setup**

```bash
cd frontend

# Install dependencies
npm install

# Configure environment (optional)
cp ../.env.example .env.local

# Start development server
npm run dev
```

4. **Open the Application**

Navigate to [http://localhost:3000](http://localhost:3000) in your browser.

### Usage

#### 1. Extract a Website

1. Go to the **Extractor** page
2. Enter a URL to extract
3. Configure extraction options (viewport, theme, etc.)
4. Click **Analyze** to start extraction
5. Once complete, click **Save to Cache** to store the result

#### 2. Clone with AI

1. Go to the **Agent** page
2. Click **Sources** button to open the source panel
3. Select a cached extraction
4. Chat with the AI to generate code
5. View live preview as the Agent writes code

## Architecture

```
nexting/
├── backend/                 # Python FastAPI backend
│   ├── cache/              # Memory cache for extractions
│   ├── extractor/          # Playwright-based web extractor
│   ├── agent/              # Multi-agent system with Claude
│   ├── boxlite/            # Backend sandbox environment
│   ├── image_proxy/        # Image proxy for CORS handling
│   └── image_downloader/   # Batch image download service
│
├── frontend/               # Next.js frontend
│   ├── src/app/           # App router pages
│   ├── src/components/    # React components
│   │   ├── ui/           # Shadcn/UI components
│   │   ├── landing/      # Landing page sections
│   │   ├── extractor/    # Extractor components
│   │   └── agent/        # Agent chat & preview
│   ├── src/hooks/        # Custom React hooks
│   └── src/lib/          # Utilities and API clients
│
├── docs/                  # Documentation & assets
│   ├── assets/           # Demo videos & images
│   ├── cn/               # Chinese documentation
│   └── ja/               # Japanese documentation
│
└── .env.example          # Environment variables template
```

## API Reference

### Extractor API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/extractor/extract` | POST | Start webpage extraction |
| `/api/extractor/status/{id}` | GET | Poll extraction status |

### Cache API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cache/store` | POST | Store extraction to cache |
| `/api/cache/list` | GET | List cached extractions |
| `/api/cache/{id}` | GET | Get cached extraction |
| `/api/cache/{id}` | DELETE | Delete cached extraction |

### Agent API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent/ws` | WebSocket | AI agent communication |

### BoxLite API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/boxlite/*` | Various | Backend sandbox environment |
| `/api/boxlite-agent/*` | Various | Agent sandbox operations |

## Tech Stack

| Category | Technologies |
|----------|--------------|
| **Frontend** | Next.js 15, React 19, TailwindCSS 4, Shadcn/UI, Three.js |
| **Backend** | FastAPI, Python 3.11+, Playwright, WebSocket |
| **AI** | Claude (Anthropic API), Multi-Agent Architecture |
| **Preview** | WebContainer (StackBlitz) |
| **Styling** | TailwindCSS, CSS Variables, Dark Mode Support |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Extract the real code, not guesses.

Made with ❤️ by [Eric Shang](https://github.com/ericshang98)

</div>
