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
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

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
    log(f"STEP 1 - Login at {PARIM_URL}/login")
    await page.goto(PARIM_URL + "/login", wait_until="networkidle", timeout=40000)
    await page.wait_for_timeout(3000)

    email_input = await page.wait_for_selector(
        'input[type="email"], input[name="email"], input[name="username"]', timeout=15000
    )
    await email_input.fill(EMAIL)
    log("STEP 2 - Email filled")

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
    log("STEP 3 - Password filled")

    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(3000)
    log(f"STEP 4 - Logged in, URL={page.url}")

async def open_shifts_page(page):
    log("STEP 5 - Go to staff page")
    await page.goto(PARIM_URL + "/staff", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    log("STEP 6 - Wait for monolith-iframe to exist in DOM")
    try:
        await page.wait_for_selector('#monolith-iframe', timeout=15000)
        log("STEP 6 - iframe found!")
    except Exception as e:
        log(f"STEP 6 - iframe NOT found: {e}")
        iframe_check = await page.evaluate("document.getElementById('monolith-iframe') ? 'exists' : 'missing'")
        log(f"STEP 6 - iframe check via JS: {iframe_check}")
        raise Exception("monolith-iframe not in DOM")

    log("STEP 7 - Set iframe src to Open Shifts")
    open_url = PARIM_URL + "/s/event/index"
    await page.evaluate(f"""
        () => {{
            const el = document.getElementById('monolith-iframe');
            el.src = '{open_url}';
        }}
    """)
    log(f"STEP 7 - iframe src set to {open_url}")

    log("STEP 8 - Wait 12s for Open Shifts to load")
    await page.wait_for_timeout(12000)
    await page.screenshot(path="screenshot_01_open_shifts.png")

    frames = page.frames
    log(f"STEP 8 - Frames after wait: {[f.url for f in frames]}")

    event_frame = None
    for f in frames:
        if "event" in f.url:
            event_frame = f
            log(f"STEP 8 - Event frame found: {f.url}")
            break

    if not event_frame and len(frames) > 1:
        event_frame = frames[1]
        log(f"STEP 8 - Using frame[1]: {event_frame.url}")

    return event_frame

async def apply_shifts(frame, page, applied):
    log("STEP 9 - Looking for Apply buttons in frame")
    await asyncio.sleep(3)

    btns = await frame.query_selector_all('button:has-text("Apply")')
    log(f"STEP 9 - Found {len(btns)} Apply button(s)")

    if not btns:
        snippet = await frame.evaluate("document.body?.innerHTML?.substring(0, 300) || 'empty'")
        log(f"STEP 9 - Frame body: {snippet}")
        return 0

    count = 0
    for i, btn in enumerate(btns):
        try:
            if not await btn.is_visible():
                continue

            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=row]') || el.parentElement?.parentElement"
                )
                text = (await row.inner_text()).strip()[:200]
            except Exception:
                text = f"shift_{i}"

            if text in applied:
                log(f"STEP 10 - Shift {i+1} already applied, skipping")
                continue

            log(f"STEP 10 - Applying shift {i+1}: {text[:60]}")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path=f"screenshot_02_modal_{i}.png")

            confirmed = False
            for sel in [
                '.modal-footer .btn-success',
                '.modal-footer button:last-child',
                '.modal .btn-success',
                '.modal button:has-text("Apply")',
                '[role="dialog"] button:has-text("Apply")',
            ]:
                try:
                    mb = await frame.query_selector(sel)
                    if mb and await mb.is_visible():
                        log(f"STEP 11 - Confirming via {sel}")
                        await mb.click()
                        await asyncio.sleep(3)
                        confirmed = True
                        break
                except Exception:
                    continue

            if confirmed:
                applied.add(text)
                save_applied(applied)
                count += 1
                log(f"STEP 11 - SUCCESS! Applied for shift {i+1}!")
                await page.screenshot(path=f"screenshot_03_done_{i}.png")
            else:
                log(f"STEP 11 - Modal confirm not found for shift {i+1}")

        except Exception as e:
            log(f"Error on shift {i+1}: {e}")

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("ERROR: Secrets not set!")
        sys.exit(1)

    log("=== PARiM Bot Starting ===")
    applied = load_applied()
    log(f"History: {len(applied)} applied shifts")

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
            frame = await open_shifts_page(page)
            if frame:
                n = await apply_shifts(frame, page, applied)
                log(f"=== Applied for {n} shift(s) this run ===")
            else:
                log("=== Could not get Open Shifts frame ===")
        except Exception as e:
            log(f"=== FATAL: {e} ===")
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
