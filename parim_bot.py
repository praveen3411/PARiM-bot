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
    log(f"Opening {login_url}")
    await page.goto(login_url, wait_until="networkidle", timeout=40000)
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
            first_item = await page.wait_for_selector('li, .team-item', timeout=5000)
            if first_item:
                await first_item.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass
    else:
        await email_input.press("Tab")
        await page.wait_for_timeout(1000)

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

    btn = await page.query_selector(
        'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
    )
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(5000)
    log(f"Logged in! URL: {page.url}")

async def load_open_shifts(page):
    staff_url = PARIM_URL.rstrip("/") + "/staff"
    log(f"Going to staff page: {staff_url}")
    await page.goto(staff_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    await page.wait_for_selector('#monolith-iframe', timeout=15000)
    log("Iframe found!")

    open_shifts_url = PARIM_URL.rstrip("/") + "/s/event/index"
    log(f"Setting iframe to Open Shifts: {open_shifts_url}")
    await page.evaluate(f"""
        document.getElementById('monolith-iframe').src = '{open_shifts_url}';
    """)
    await page.wait_for_timeout(8000)
    await page.screenshot(path="screenshot_01_open_shifts.png")
    log("Open Shifts page loaded")

async def apply_for_shifts(page, applied):
    count = 0
    frame = page.frame_locator('#monolith-iframe')

    apply_locator = frame.locator('button:has-text("Apply")')
    total = await apply_locator.count()
    log(f"Found {total} Apply button(s) via frame_locator")

    if total == 0:
        log("No available shifts to apply for")
        return 0

    for i in range(total):
        try:
            btns = frame.locator('button:has-text("Apply")')
            n = await btns.count()
            if n == 0:
                break

            btn = btns.first
            visible = await btn.is_visible()
            if not visible:
                log(f"Button {i+1} not visible, skipping")
                continue

            try:
                text = await btn.evaluate(
                    "el => (el.closest('tr') || el.closest('[class*=row]') || el.parentElement?.parentElement)?.innerText || ''"
                )
                shift_id = text.strip()[:200]
            except Exception:
                shift_id = f"shift_{i}"

            if shift_id and shift_id in applied:
                log(f"Already applied - skipping")
                continue

            log(f"Clicking Apply for shift {i+1}...")
            await btn.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path=f"screenshot_0{i+2}_modal.png")

            confirmed = False
            for modal_sel in [
                '.modal button:has-text("Apply")',
                '[role="dialog"] button:has-text("Apply")',
                'dialog button:has-text("Apply")',
                '.modal-footer button:has-text("Apply")',
                'button.btn-success',
                'button.btn-primary',
            ]:
                try:
                    modal_btn = frame.locator(modal_sel).first
                    if await modal_btn.count() > 0 and await modal_btn.is_visible():
                        log("Confirming in modal...")
                        await modal_btn.click()
                        await page.wait_for_timeout(3000)
                        confirmed = True
                        break
                except Exception:
                    continue

            if not confirmed:
                new_btns = frame.locator('button:has-text("Apply")')
                new_count = await new_btns.count()
                if new_count > 0:
                    for j in range(new_count):
                        b = new_btns.nth(j)
                        if await b.is_visible():
                            await b.click()
                            await page.wait_for_timeout(2000)
                            confirmed = True
                            break

            if confirmed:
                if shift_id:
                    applied.add(shift_id)
                    save_applied(applied)
                count += 1
                log(f"SUCCESS - Applied for shift {i+1}!")
                await page.screenshot(path=f"screenshot_success_{i+1}.png")
            else:
                log(f"Could not confirm modal for shift {i+1}")

            await page.wait_for_timeout(2000)

        except Exception as e:
            log(f"Error on shift {i+1}: {e}")

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("PARIM_EMAIL or PARIM_PASSWORD not set!")
        sys.exit(1)

    log("PARiM Auto-Apply Bot - Starting")
    applied = load_applied()
    log(f"History: {len(applied)} previously-applied shifts")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        try:
            await login(page)
            await load_open_shifts(page)
            n = await apply_for_shifts(page, applied)
            if n:
                log(f"SUCCESS - Applied for {n} new shift(s)!")
            else:
                log("Run complete - no new shifts to apply for")
        except Exception as e:
            log(f"Error: {e}")
            try:
                await page.screenshot(path="screenshot_error.png")
            except Exception:
                pass
            sys.exit(1)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
