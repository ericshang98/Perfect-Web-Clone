#!/usr/bin/env python3
"""
Capture screenshots for showcase gallery.
Usage: python capture_showcase_screenshots.py <project_id> <checkpoint_id> <output_dir>

This script:
1. Restores a checkpoint via the API
2. Captures the website preview screenshot
3. Captures the chat panel screenshot
"""

import asyncio
import sys
import os
import httpx
from pathlib import Path
from playwright.async_api import async_playwright

# Backend API URL
API_BASE = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"
PREVIEW_URL = "http://localhost:8080"


async def wait_for_server(url: str, timeout: int = 30) -> bool:
    """Wait for a server to become available."""
    async with httpx.AsyncClient() as client:
        for _ in range(timeout):
            try:
                response = await client.get(url, timeout=2.0)
                if response.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False


async def create_sandbox() -> str:
    """Create a new sandbox and return its ID."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/boxlite/sandbox",
            json={"name": "screenshot-capture"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return data["sandbox_id"]


async def restore_checkpoint(sandbox_id: str, project_id: str, checkpoint_id: str) -> dict:
    """Restore a checkpoint to the sandbox."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE}/boxlite/sandbox/{sandbox_id}/restore",
            json={"project_id": project_id, "checkpoint_id": checkpoint_id},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()


async def capture_screenshots(project_id: str, checkpoint_id: str, output_dir: str):
    """Main function to capture screenshots."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Creating sandbox...")
    sandbox_id = await create_sandbox()
    print(f"Created sandbox: {sandbox_id}")

    print(f"Restoring checkpoint {checkpoint_id} from project {project_id}...")
    result = await restore_checkpoint(sandbox_id, project_id, checkpoint_id)
    print(f"Checkpoint restored: {result}")

    # Wait for preview server to be ready
    print(f"Waiting for preview server at {PREVIEW_URL}...")
    if not await wait_for_server(PREVIEW_URL, timeout=30):
        print("Warning: Preview server may not be ready, attempting screenshot anyway...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # Capture website preview
        print("Capturing website preview...")
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        try:
            await page.goto(PREVIEW_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)  # Wait for any animations
            website_path = output_path / "website.png"
            await page.screenshot(path=str(website_path), full_page=False)
            print(f"Saved website screenshot to {website_path}")
        except Exception as e:
            print(f"Failed to capture website preview: {e}")
        await page.close()

        # Capture chat panel from boxlite-agent page
        print("Capturing chat panel...")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            agent_url = f"{FRONTEND_URL}/boxlite-agent?checkpoint={checkpoint_id}&project={project_id}"
            await page.goto(agent_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(5)  # Wait for checkpoint to restore

            # Try to find and screenshot just the chat panel
            chat_panel = page.locator('[data-testid="chat-panel"]').first
            if await chat_panel.count() > 0:
                chat_path = output_path / "chat.png"
                await chat_panel.screenshot(path=str(chat_path))
                print(f"Saved chat panel screenshot to {chat_path}")
            else:
                # Fall back to full page screenshot
                chat_path = output_path / "chat.png"
                await page.screenshot(path=str(chat_path), full_page=False)
                print(f"Saved full page screenshot to {chat_path} (chat panel not found)")
        except Exception as e:
            print(f"Failed to capture chat panel: {e}")

        await browser.close()

    print("Done!")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python capture_showcase_screenshots.py <project_id> <checkpoint_id> <output_dir>")
        print("Example: python capture_showcase_screenshots.py did-global-cinema-aaf71f95 cp_005 ../frontend/public/showcases/did-global-cinema")
        sys.exit(1)

    project_id = sys.argv[1]
    checkpoint_id = sys.argv[2]
    output_dir = sys.argv[3]

    asyncio.run(capture_screenshots(project_id, checkpoint_id, output_dir))
