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

def log(msg, icon="INFO"):
    ts = datetime.utcnow().strftime("%H:%M:%S UTC")
    print(f"[{ts}] {icon} {msg}", flush=True)

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
    login_url = PARIM_URL.rstrip("/") + "/login"
    log(f"Step 1: Opening {login_url}")
    await page.goto(login_url, wait_until="networkidle", timeout=40000)
    await page.wait_for_timeout(3000)

    email_input = await page.wait_for_selector(
        'input[type="email"], input[name="email"], input[name="username"]', timeout=15000
    )
    await email_input.fill(EMAIL)
    log("Step 2: Email entered")

    next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
    if next_btn:
        await next_btn.click()
        await page.wait_for_timeout(3000)
        try:
            first_item = await page.wait_for_selector('li, .team-item', timeout=5000)
            if first_item:
                await first_item.click()
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
        raise Exception("Could not find password field")

    await pw_input.fill(PASSWORD)
    log("Step 3: Password entered")

    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(5000)
    log(f"Step 4: Logged in! URL={page.url}")

async def get_open_shifts_frame(page):
    staff_url = PARIM_URL.rstrip("/") + "/staff"
    log(f"Step 5: Loading {staff_url}")
    await page.goto(staff_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    log(f"Step 6: Current frames: {[f.url for f in page.frames]}")

    open_shifts_url = PARIM_URL.rstrip("/") + "/s/event/index"
    log(f"Step 7: Setting iframe src to {open_shifts_url}")
    await page.evaluate(f"document.getElementById('monolith-iframe').src = '{open_shifts_url}';")

    log("Step 8: Waiting for event frame to load (up to 20s)...")
    event_frame = None
    for i in range(20):
        await asyncio.sleep(1)
        frames = page.frames
        for f in frames:
            if "event" in f.url or "event" in f.url.lower():
                event_frame = f
                log(f"Found event frame at attempt {i+1}: {f.url}")
                break
        if event_frame:
            break
        if i % 5 == 0:
            log(f"  Still waiting... frames: {[f.url for f in page.frames]}")

    if not event_frame:
        log("Event frame not found by URL - using frames[-1]")
        log(f"All frames: {[f.url for f in page.frames]}")
        if len(page.frames) > 1:
            event_frame = page.frames[-1]
            log(f"Using frame: {event_frame.url}")

    await page.screenshot(path="screenshot_01_state.png")
    return event_frame

async def apply_via_frame(frame, page, applied):
    count = 0
    log(f"Step 9: Querying Apply buttons in frame {frame.url}")
    await asyncio.sleep(5)

    apply_btns = await frame.query_selector_all('button:has-text("Apply")')
    log(f"Step 10: Found {len(apply_btns)} Apply buttons in frame")

    if not apply_btns:
        html_snippet = await frame.evaluate("document.body.innerHTML.substring(0, 500)")
        log(f"Frame body snippet: {html_snippet}")
        return 0

    for i, btn in enumerate(apply_btns):
        try:
            visible = await btn.is_visible()
            log(f"Button {i+1}: visible={visible}")
            if not visible:
                continue

            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=row]') || el.parentElement?.parentElement"
                )
                text = (await row.inner_text()).strip()
            except Exception:
                text = f"shift_{i}"

            shift_id = text[:200]
            if shift_id in applied:
                log(f"Already applied - skipping")
                continue

            log(f"Step 11: Clicking Apply for: {text[:80]}...")
            await btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path=f"screenshot_02_modal_{i}.png")

            confirmed = False
            for sel in [
                '.modal-footer .btn-success',
                '.modal-footer button:last-child',
                '.modal button.btn-success',
                '[role="dialog"] button:has-text("Apply")',
                '.modal button:has-text("Apply")',
            ]:
                try:
                    mb = await frame.query_selector(sel)
                    if mb and await mb.is_visible():
                        log(f"Clicking modal confirm via: {sel}")
                        await mb.click()
                        await asyncio.sleep(3)
                        confirmed = True
                        break
                except Exception:
                    continue

            if confirmed:
                applied.add(shift_id)
                save_applied(applied)
                count += 1
                log(f"SUCCESS! Applied for shift {i+1}!")
                await page.screenshot(path=f"screenshot_03_success_{i}.png")
            else:
                log(f"Could not find confirm button for shift {i+1}")

        except Exception as e:
            log(f"Error on shift {i+1}: {e}")

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("PARIM_EMAIL or PARIM_PASSWORD not set!")
        sys.exit(1)

    log("=== PARiM Auto-Apply Bot Starting ===")
    applied = load_applied()
    log(f"History: {len(applied)} previously applied shifts")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-web-security", "--allow-running-insecure-content"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        try:
            await login(page)
            frame = await get_open_shifts_frame(page)

            if frame:
                n = await apply_via_frame(frame, page, applied)
                if n:
                    log(f"=== SUCCESS: Applied for {n} shift(s)! ===")
                else:
                    log("=== Done: No new shifts to apply for ===")
            else:
                log("=== ERROR: Could not find Open Shifts frame ===")

        except Exception as e:
            log(f"=== FATAL ERROR: {e} ===")
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
