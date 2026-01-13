#!/usr/bin/env python3
"""
Simple script to capture a website screenshot using Playwright.
Usage: python capture_website_screenshot.py <url> <output_path>
"""

import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright


async def capture_screenshot(url: str, output_path: str, width: int = 1280, height: int = 720):
    """Capture a screenshot of a website."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height})

        try:
            print(f"Loading {url}...")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)  # Wait for animations

            print(f"Capturing screenshot...")
            await page.screenshot(path=str(output), full_page=False)
            print(f"Saved to {output}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python capture_website_screenshot.py <url> <output_path>")
        print("Example: python capture_website_screenshot.py https://example.com screenshot.png")
        sys.exit(1)

    url = sys.argv[1]
    output_path = sys.argv[2]
    asyncio.run(capture_screenshot(url, output_path))
