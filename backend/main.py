"""
Perfect Web Clone Backend
统一 FastAPI 入口

AI-powered web page extraction and cloning service.
Open-source version without authentication.

启动方式:
    python main.py
    或
    uvicorn main:app --reload --port 5100
"""

import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Perfect Web Clone API",
    description="AI-powered web page extraction and cloning",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration - allow all for open-source version
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Register Routers
# ============================================

# Cache module (memory storage for extractions)
from cache import cache_router
app.include_router(cache_router)
logger.info("Registered: /api/cache/*")

# Extractor module (Playwright page extraction)
from extractor import extractor_router
app.include_router(extractor_router)
logger.info("Registered: /api/extractor/*")

# Agent module (WebSocket for clone agent)
from agent import agent_ws_router
app.include_router(agent_ws_router)
logger.info("Registered: /api/agent/*")

# Image proxy module (CORS proxy for images)
try:
    from image_proxy.routes import router as image_proxy_router
    app.include_router(image_proxy_router)
    logger.info("Registered: /api/image-proxy/*")
except ImportError as e:
    logger.warning(f"Image proxy module not available: {e}")

# Image downloader module (batch image download)
try:
    from image_downloader.routes_fastapi import router as image_downloader_router
    app.include_router(image_downloader_router)
    logger.info("Registered: /api/image-downloader/*")
except ImportError as e:
    logger.warning(f"Image downloader module not available: {e}")

# BoxLite module (backend sandbox environment)
try:
    from boxlite import boxlite_router, boxlite_ws_router
    from boxlite.routes import boxlite_agent_router
    app.include_router(boxlite_router)
    app.include_router(boxlite_ws_router)
    app.include_router(boxlite_agent_router)
    logger.info("Registered: /api/boxlite/*")
    logger.info("Registered: /api/boxlite/ws/*")
    logger.info("Registered: /api/boxlite-agent/*")
except ImportError as e:
    logger.warning(f"BoxLite module not available: {e}")

# Sources module (file-system based source storage)
try:
    from sources import sources_router
    app.include_router(sources_router)
    logger.info("Registered: /api/sources/*")
except ImportError as e:
    logger.warning(f"Sources module not available: {e}")

# Checkpoint module (project state checkpoints)
try:
    from checkpoint.routes import router as checkpoint_router
    app.include_router(checkpoint_router)
    logger.info("Registered: /api/checkpoints/*")
except ImportError as e:
    logger.warning(f"Checkpoint module not available: {e}")


# ============================================
# Root Endpoints
# ============================================

@app.get("/")
async def root():
    """Root endpoint - API info"""
    return {
        "name": "Perfect Web Clone API",
        "version": "1.0.0",
        "description": "AI-powered web page extraction and cloning",
        "docs": "/docs",
        "endpoints": {
            "cache": "/api/cache",
            "extractor": "/api/extractor",
            "agent": "/api/agent",
            "boxlite": "/api/boxlite",
            "boxlite_agent": "/api/boxlite-agent",
            "sources": "/api/sources",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "perfect-web-clone",
        "version": "1.0.0",
    }


# ============================================
# Project Naming API
# ============================================

class ProjectNameRequest(BaseModel):
    message: str


@app.post("/api/project-name")
async def generate_project_name(request: ProjectNameRequest):
    """
    Generate a short project name based on user intent.
    Uses Claude haiku for fast, low-cost naming.
    """
    try:
        # Get API key (support both direct and proxy)
        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_PROXY_API_KEY")
        base_url = os.getenv("CLAUDE_PROXY_BASE_URL")

        if not api_key:
            logger.warning("No API key for project naming")
            return {"name": "Untitled Project"}

        # Create Anthropic client
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = anthropic.Anthropic(**client_kwargs)

        # Simple prompt for naming
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=50,
            messages=[
                {
                    "role": "user",
                    "content": f"Based on this user intent, generate a short project name (2-5 words). Only return the name, nothing else.\n\nUser intent: {request.message}"
                }
            ]
        )

        # Extract the name from response
        name = response.content[0].text.strip()

        # Clean up the name (remove quotes if any)
        name = name.strip('"\'')

        logger.info(f"Generated project name: {name}")
        return {"name": name}

    except Exception as e:
        logger.error(f"Error generating project name: {e}")
        return {"name": "Untitled Project"}


# ============================================
# Startup/Shutdown Events
# ============================================

async def kill_port(port: int) -> bool:
    """Kill any process using the specified port"""
    import subprocess
    try:
        # Find process using the port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True
        )
        pids = result.stdout.strip().split('\n')

        killed = False
        for pid in pids:
            if pid.strip():
                try:
                    subprocess.run(["kill", "-9", pid.strip()], check=True)
                    logger.info(f"Killed process {pid} on port {port}")
                    killed = True
                except Exception as e:
                    logger.warning(f"Failed to kill process {pid}: {e}")

        return killed
    except Exception as e:
        logger.warning(f"Error checking port {port}: {e}")
        return False


@app.on_event("startup")
async def startup_event():
    """Run on startup"""
    logger.info("=" * 50)
    logger.info("Perfect Web Clone API Starting...")
    logger.info("=" * 50)

    # Clean up BoxLite dev server port (8080) on startup
    dev_port = int(os.getenv("BOXLITE_DEV_PORT", "8080"))
    logger.info(f"Cleaning up port {dev_port} for BoxLite dev server...")
    await kill_port(dev_port)

    # Check required environment variables (support both direct and proxy API)
    has_api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_PROXY_API_KEY")
    if not has_api_key:
        logger.warning("No API key set (ANTHROPIC_API_KEY or CLAUDE_PROXY_API_KEY) - Agent features will not work!")
    else:
        if os.getenv("CLAUDE_PROXY_API_KEY"):
            logger.info("Using Claude proxy API")

    port_for_log = os.getenv("PORT", "5100")
    logger.info(f"API documentation available at: http://localhost:{port_for_log}/docs")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on shutdown"""
    logger.info("Perfect Web Clone API Shutting down...")

    # Cleanup Playwright browser
    try:
        from extractor import playwright_extractor_service
        await playwright_extractor_service.close()
        logger.info("Playwright browser closed")
    except Exception as e:
        logger.warning(f"Error closing Playwright: {e}")


# ============================================
# Main Entry Point
# ============================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "5100"))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
