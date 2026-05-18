import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EMAIL = os.environ.get("PARIM_EMAIL", "")
PASSWORD = os.environ.get("PARIM_PASSWORD", "")
PARIM_URL = os.environ.get("PARIM_URL", "https://swordsecurityhq.parim.co")
APPLIED_FILE = Path("applied_shifts.json")

def log(msg):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)

def load_applied():
    if APPLIED_FILE.exists():
        try:
            return set(json.loads(APPLIED_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_applied(applied):
    APPLIED_FILE.write_text(json.dumps(sorted(applied)))

async def login(page):
    log("Logging in...")
    await page.goto(PARIM_URL + "/login", wait_until="load", timeout=40000)
    await page.wait_for_timeout(3000)

    email_input = await page.wait_for_selector(
        'input[type="email"], input[name="email"], input[name="username"]', timeout=15000
    )
    await email_input.fill(EMAIL)

    next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
    if next_btn:
        await next_btn.click()
        await page.wait_for_timeout(3000)
        try:
            item = await page.wait_for_selector('li, .team-item', timeout=5000)
            if item:
                await item.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass

    pw_input = None
    for sel in ['input[type="password"]', 'input[name="password"]']:
        try:
            pw_input = await page.wait_for_selector(sel, timeout=8000)
            if pw_input:
                break
        except Exception:
            continue
    if not pw_input:
        raise Exception("Password field not found")

    await pw_input.fill(PASSWORD)
    btn = await page.query_selector(
        'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
    )
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("load", timeout=30000)
    await page.wait_for_timeout(5000)
    log(f"Logged in! URL={page.url}")

async def main():
    if not EMAIL or not PASSWORD:
        log("Secrets not set!")
        sys.exit(1)

    log("=== PARiM Auto-Apply Bot ===")
    applied = load_applied()
    log(f"Previously applied: {len(applied)} shifts")

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await (await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )).new_page()

        try:
            await login(page)

            if "/staff" not in page.url:
                await page.goto(PARIM_URL + "/staff", wait_until="load", timeout=30000)
            await page.wait_for_timeout(6000)

            # Find monolith frame
            mf = None
            for f in page.frames:
                if "/s/" in f.url:
                    mf = f
                    break
            if not mf and len(page.frames) > 1:
                mf = page.frames[1]
            if not mf:
                raise Exception("Monolith frame not found")
            log(f"Frame: {mf.url}")

            # Navigate to Open Shifts
            await mf.goto(PARIM_URL + "/s/event/index", wait_until="load", timeout=20000)
            await asyncio.sleep(8)
            log(f"Open Shifts loaded: {mf.url}")
            await page.screenshot(path="screenshot_01_open_shifts.png")

            total = 0

            for attempt in range(20):
                # Find visible Apply buttons using Playwright locator (NOT JavaScript click)
                apply_locator = mf.locator('a.apply:visible')
                count = await apply_locator.count()
                log(f"Attempt {attempt+1}: {count} available shift(s)")

                if count == 0:
                    log("No more available shifts")
                    break

                # Get shift info for tracking
                try:
                    first_btn = apply_locator.first
                    shift_label = await first_btn.evaluate(
                        "el => (el.closest('.venue-wrap') || el.closest('.row') || el.parentElement)?.innerText?.trim()?.substring(0,80) || 'shift'"
                    )
                    shift_id = await first_btn.get_attribute('data-shift-id') or \
                               await first_btn.get_attribute('data-team-id') or \
                               shift_label[:50]
                except Exception:
                    shift_label = f"shift_{attempt}"
                    shift_id = shift_label

                if shift_id in applied:
                    log(f"Already applied: {shift_id} - skipping")
                    # Try next one - remove from visible list somehow
                    # Just break to avoid infinite loop
                    break

                log(f"Applying: {shift_label[:60]}")

                # Use Playwright's proper click - triggers jQuery AJAX handlers
                try:
                    await first_btn.scroll_into_view_if_needed()
                    await first_btn.click()
                    log("Apply button clicked via Playwright")
                except Exception as e:
                    log(f"Click failed: {e}")
                    continue

                await asyncio.sleep(3)
                await page.screenshot(path=f"screenshot_02_modal_{attempt}.png")

                # Wait for modal ok-btn to become visible and click it
                try:
                    ok_btn = mf.locator('a#ok-btn:visible')
                    ok_count = await ok_btn.count()
                    log(f"ok-btn visible: {ok_count}")

                    if ok_count > 0:
                        await ok_btn.first.click()
                        log("ok-btn clicked via Playwright")
                        await asyncio.sleep(4)

                        # Verify the shift is now Submitted (Apply button gone)
                        new_count = await mf.locator('a.apply:visible').count()
                        log(f"Apply buttons after submit: {new_count}")

                        if new_count < count:
                            applied.add(shift_id)
                            save_applied(applied)
                            total += 1
                            log(f"SUCCESS! Shift submitted! ({count} -> {new_count} remaining)")
                            await page.screenshot(path=f"screenshot_done_{total}.png")
                        else:
                            log("Button count unchanged - submission may have failed")
                            # Still track to avoid retrying
                            applied.add(shift_id)
                            save_applied(applied)
                    else:
                        log("ok-btn not visible - modal may not have opened")
                        # Dismiss any dialog and continue
                        try:
                            cancel = mf.locator('#no-btn:visible')
                            if await cancel.count() > 0:
                                await cancel.first.click()
                        except Exception:
                            pass
                        await asyncio.sleep(2)

                except Exception as e:
                    log(f"Modal error: {e}")

                await asyncio.sleep(2)

            log(f"=== Applied for {total} new shift(s) this run ===")

        except Exception as e:
            log(f"ERROR: {e}")
            import traceback
            log(traceback.format_exc())
            try:
                await page.screenshot(path="screenshot_error.png")
            except Exception:
                pass
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
