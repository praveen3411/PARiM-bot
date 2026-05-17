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

    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    staff_url = PARIM_URL.rstrip("/") + "/staff"
    if "/staff" not in page.url:
        await page.goto(staff_url, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(5000)

    log(f"Logged in! URL: {page.url}")

async def get_open_shifts_frame(page):
    open_shifts_url = PARIM_URL.rstrip("/") + "/s/event/index"
    log(f"Navigating iframe to Open Shifts: {open_shifts_url}")

    await page.evaluate(f"""
        () => {{
            const iframe = document.getElementById('monolith-iframe');
            if (iframe) {{
                iframe.src = '{open_shifts_url}';
                return 'iframe src updated';
            }}
            return 'iframe not found';
        }}
    """)

    await page.wait_for_timeout(5000)
    await page.screenshot(path="screenshot_01_after_iframe_nav.png")

    for frame in page.frames:
        log(f"Frame URL: {frame.url}")
        if "event" in frame.url or "open" in frame.url.lower():
            log(f"Found Open Shifts frame: {frame.url}")
            return frame

    if len(page.frames) > 1:
        frame = page.frames[1]
        log(f"Using second frame: {frame.url}")
        return frame

    return None

async def apply_for_shifts(frame, page, applied):
    count = 0
    await asyncio.sleep(3)

    content = await frame.content()
    log(f"Frame has Apply: {'Apply' in content}")
    log(f"Frame has Available: {'Available' in content}")

    await page.screenshot(path="screenshot_02_frame_content.png")

    apply_btns = await frame.query_selector_all('button:has-text("Apply")')
    log(f"Found {len(apply_btns)} Apply button(s) in frame")

    if not apply_btns:
        log("No Apply buttons found in frame")
        return 0

    for i, btn in enumerate(apply_btns):
        try:
            if not await btn.is_visible() or not await btn.is_enabled():
                continue

            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=row]') || el.parentElement.parentElement"
                )
                text = (await row.inner_text()).strip()
            except Exception:
                text = f"shift_{i}"

            shift_id = text[:200]
            if shift_id in applied:
                log(f"Already applied - skipping")
                continue

            log(f"Applying shift {i+1}: {text[:80]}...")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path=f"screenshot_03_modal_{i}.png")

            confirmed = False
            for confirm_sel in [
                '.modal button:has-text("Apply")',
                '[role="dialog"] button:has-text("Apply")',
                'dialog button:has-text("Apply")',
                'button.btn-success',
                'button.btn-primary',
            ]:
                try:
                    mb = await frame.wait_for_selector(confirm_sel, timeout=3000)
                    if mb and await mb.is_visible():
                        await mb.click()
                        await asyncio.sleep(3)
                        confirmed = True
                        break
                except Exception:
                    continue

            if not confirmed:
                confirmed = await frame.evaluate("""
                    () => {
                        const btns = Array.from(document.querySelectorAll('button'));
                        const applyBtn = btns.find(b => b.textContent.trim() === 'Apply' && b.offsetParent !== null);
                        if (applyBtn) { applyBtn.click(); return true; }
                        return false;
                    }
                """)
                if confirmed:
                    await asyncio.sleep(2)

            if confirmed:
                applied.add(shift_id)
                save_applied(applied)
                count += 1
                log(f"SUCCESS - Applied for shift {i+1}!")
                await page.screenshot(path=f"screenshot_04_success_{i}.png")

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
            frame = await get_open_shifts_frame(page)

            if frame:
                n = await apply_for_shifts(frame, page, applied)
                if n:
                    log(f"SUCCESS - Applied for {n} new shift(s)!")
                else:
                    log("Run complete - no new shifts to apply for")
            else:
                log("Could not find iframe frame")
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
