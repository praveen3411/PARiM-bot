"""
PARiM Auto-Apply Bot — Cloud Version
=====================================
Runs on GitHub Actions every 5 minutes.
Credentials are stored securely as GitHub Secrets (never in the code).
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Credentials come from GitHub Secrets (set once, stored securely) ──
EMAIL    = os.environ.get("PARIM_EMAIL", "")
PASSWORD = os.environ.get("PARIM_PASSWORD", "")
PARIM_URL = os.environ.get("PARIM_URL", "https://login.parim.co")

# File to track applied shifts (persists in GitHub Actions cache)
APPLIED_FILE = Path("applied_shifts.json")


def log(msg, icon="ℹ️"):
    ts = datetime.utcnow().strftime("%H:%M:%S UTC")
    print(f"[{ts}] {icon}  {msg}", flush=True)


def load_applied() -> set:
    if APPLIED_FILE.exists():
        try:
            return set(json.loads(APPLIED_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_applied(applied: set):
    APPLIED_FILE.write_text(json.dumps(sorted(applied)))


async def login(page):
    log(f"Opening {PARIM_URL} ...")
    await page.goto(PARIM_URL, wait_until="networkidle", timeout=40000)

    # Email field
    email_sel = 'input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email" i]'
    email_input = await page.wait_for_selector(email_sel, timeout=15000)
    await email_input.fill(EMAIL)

    # Password field
    pw_input = await page.wait_for_selector('input[type="password"]', timeout=10000)
    await pw_input.fill(PASSWORD)

    # Submit
    btn = await page.query_selector(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Log in"), button:has-text("Sign in"), '
        'button:has-text("Login")'
    )
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=25000)
    log("Logged in!", "✅")


async def go_to_open_shifts(page) -> bool:
    """Navigate to the Open Shifts section."""
    selectors = [
        'a:has-text("Open Shifts")',
        'a:has-text("Open shifts")',
        'li:has-text("Open Shifts") a',
        'nav a[href*="open"]',
        'nav a[href*="shift"]',
        '.sidebar a:has-text("Shift")',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=12000)
                log("On Open Shifts page")
                return True
        except Exception:
            pass

    # Fallback: try URL patterns
    base = "/".join(page.url.split("/")[:3])
    for path in ["/shifts/open", "/open-shifts", "/shifts", "/employee/shifts"]:
        try:
            await page.goto(base + path, wait_until="networkidle", timeout=12000)
            log(f"Navigated to {base + path}")
            return True
        except Exception:
            pass

    log("Could not reach Open Shifts page", "⚠️")
    return False


async def apply_for_shifts(page, applied: set) -> int:
    """Find all Apply buttons and click them for unseen shifts."""
    count = 0

    apply_btns = await page.query_selector_all(
        'button:has-text("Apply"), '
        'a.btn:has-text("Apply"), '
        '.apply-btn, [data-action="apply"], '
        'button.green:has-text("Apply")'
    )

    if not apply_btns:
        log("No open shifts right now — nothing to apply for")
        return 0

    log(f"Found {len(apply_btns)} open shift(s)!", "📋")

    for btn in apply_btns:
        try:
            # Build a unique ID from the surrounding shift info
            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=shift]') "
                    "|| el.closest('li') || el.parentElement"
                )
                text = (await row.inner_text()).strip()
            except Exception:
                text = (await btn.inner_text()).strip()

            shift_id = text[:200]

            if shift_id in applied:
                log(f"Already applied: {shift_id[:60]}... skipping")
                continue

            log(f"Applying: {shift_id[:80]}...")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(2000)

            # Confirm dialog (second Apply / Confirm / Yes button)
            for confirm_sel in [
                'button:has-text("Apply")',
                'button:has-text("Confirm")',
                'button:has-text("Yes")',
                '.modal button.btn-primary',
                '.dialog button',
            ]:
                cb = await page.query_selector(confirm_sel)
                if cb and await cb.is_visible():
                    await cb.click()
                    await page.wait_for_timeout(2000)
                    break

            applied.add(shift_id)
            save_applied(applied)
            count += 1
            log(f"Applied successfully! 🎉", "✅")
            await page.wait_for_timeout(1000)

        except Exception as e:
            log(f"Could not apply for a shift: {e}", "⚠️")

    return count


async def main():
    if not EMAIL or not PASSWORD:
        log("PARIM_EMAIL or PARIM_PASSWORD not set in environment!", "❌")
        log("Add them as GitHub Secrets — see README.md")
        sys.exit(1)

    log("=" * 50)
    log("PARiM Auto-Apply Bot  (Cloud Edition)")
    log("=" * 50)

    applied = load_applied()
    log(f"History: {len(applied)} previously-applied shifts loaded")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("Playwright not installed", "❌")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            )
        )
        page = await context.new_page()

        try:
            await login(page)
            ok = await go_to_open_shifts(page)
            if ok:
                n = await apply_for_shifts(page, applied)
                if n:
                    log(f"✅ Applied for {n} new shift(s) this run!", "🎉")
                else:
                    log("Run complete — no new shifts this time")
        except Exception as e:
            log(f"Error: {e}", "❌")
            # Save a screenshot for debugging
            try:
                await page.screenshot(path="error_screenshot.png")
                log("Saved error_screenshot.png for debugging")
            except Exception:
                pass
            sys.exit(1)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
