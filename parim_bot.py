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
    log(f"LOGIN - {PARIM_URL}/login")
    await page.goto(PARIM_URL + "/login", wait_until="networkidle", timeout=40000)
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
            if pw_input: break
        except Exception:
            continue
    if not pw_input:
        raise Exception("Password field not found")

    await pw_input.fill(PASSWORD)

    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(3000)
    log(f"LOGIN DONE - {page.url}")

async def get_monolith_frame(page):
    log("Going to /staff to load monolith iframe")
    await page.goto(PARIM_URL + "/staff", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    log(f"Frames after /staff: {[f.url for f in page.frames]}")

    monolith = None
    for f in page.frames:
        if "/s/" in f.url or "parim.co/s" in f.url:
            monolith = f
            log(f"Found monolith frame: {f.url}")
            break

    if not monolith and len(page.frames) > 1:
        monolith = page.frames[1]
        log(f"Using frames[1]: {monolith.url}")

    if not monolith:
        raise Exception("Could not find monolith frame")

    return monolith

async def navigate_frame_to_open_shifts(monolith, page):
    open_url = PARIM_URL + "/s/event/index"
    log(f"Navigating FRAME directly to {open_url}")

    # Use frame.goto() - the proper Playwright way!
    await monolith.goto(open_url, wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(5000)

    log(f"Frame URL after goto: {monolith.url}")
    await page.screenshot(path="screenshot_01_open_shifts.png")

    content = await monolith.content()
    log(f"Frame has Apply: {'Apply' in content}")
    log(f"Frame has Available: {'Available' in content}")
    return "Apply" in content or "Available" in content

async def apply_shifts(monolith, page, applied):
    count = 0
    log("Looking for Apply buttons...")

    btns = await monolith.query_selector_all('button:has-text("Apply")')
    log(f"Found {len(btns)} Apply button(s)")

    if not btns:
        snippet = await monolith.evaluate("document.body.innerText.substring(0, 300)")
        log(f"Page text: {snippet}")
        return 0

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
                log(f"Already applied - skipping shift {i+1}")
                continue

            log(f"Applying shift {i+1}: {text[:80]}")
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
                    mb = await monolith.query_selector(sel)
                    if mb and await mb.is_visible():
                        log(f"Confirming via {sel}")
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
                log(f"SUCCESS! Applied for shift {i+1}!")
                await page.screenshot(path=f"screenshot_03_done_{i}.png")
            else:
                log(f"No confirm button found for shift {i+1}")

        except Exception as e:
            log(f"Error shift {i+1}: {e}")

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("Secrets not set!")
        sys.exit(1)

    log("=== PARiM Bot Starting ===")
    applied = load_applied()
    log(f"History: {len(applied)} shifts")

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
            monolith = await get_monolith_frame(page)
            ok = await navigate_frame_to_open_shifts(monolith, page)
            if ok:
                n = await apply_shifts(monolith, page, applied)
                log(f"=== Applied for {n} shift(s) ===")
            else:
                log("=== Open Shifts page did not load ===")
        except Exception as e:
            log(f"=== ERROR: {e} ===")
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
