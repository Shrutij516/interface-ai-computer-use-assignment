"""Captures the current page state: an ARIA accessibility-tree snapshot as
the primary signal, plus a screenshot as backup — per
interface-ai-project-spec.md §2."""

import base64
from pathlib import Path

from playwright.sync_api import Page


def capture_state(page: Page, screenshots_dir: Path, step_index: int) -> dict:
    screenshot_path = screenshots_dir / f"step_{step_index}.png"
    page.screenshot(path=str(screenshot_path))
    screenshot_b64 = base64.standard_b64encode(screenshot_path.read_bytes()).decode("utf-8")

    accessibility_tree = page.locator("body").aria_snapshot()

    return {
        "url": page.url,
        "title": page.title(),
        "accessibility_tree": accessibility_tree,
        "screenshot_path": screenshot_path,
        "screenshot_base64": screenshot_b64,
    }
