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
    log("Email entered")

    next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
    if next_btn:
        log("Clicking Next...")
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
    log("Password entered")

    btn = await page.query_selector(
        'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
    )
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(4000)

    staff_url = PARIM_URL.rstrip("/") + "/staff"
    if "/staff" not in page.url:
        await page.goto(staff_url, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(3000)

    await page.screenshot(path="screenshot_01_dashboard.png")
    log(f"Logged in! URL: {page.url}")

async def go_to_open_shifts(page):
    log("Navigating to Open Shifts using JavaScript click...")

    clicked = await page.evaluate("""
        () => {
            const allElements = document.querySelectorAll('a, li, div, span, button, nav *');
            for (const el of allElements) {
                const text = el.textContent.trim();
                if (text === 'Open Shifts' || text === 'Open shifts') {
                    el.click();
                    return 'clicked: ' + el.tagName + ' - ' + el.className;
                }
            }
            return 'not found';
        }
    """)
    log(f"JS click result: {clicked}")
    await page.wait_for_timeout(5000)
    await page.screenshot(path="screenshot_02_after_nav.png")
    log(f"URL after nav: {page.url}")

    content = await page.content()
    if "Apply" in content or "Available" in content or "open" in page.url.lower():
        log("Open Shifts page loaded!")
        return True

    log("Trying direct URL navigation...")
    for path in ["/staff/open-shifts", "/staff#open-shifts", "/open-shifts"]:
        try:
            url = PARIM_URL.rstrip("/") + path
            await page.goto(url, wait_until="networkidle", timeout=10000)
            await page.wait_for_timeout(3000)
            content = await page.content()
            if "Apply" in content or "Available" in content:
                log(f"Found shifts at {url}")
                await page.screenshot(path="screenshot_02_after_nav.png")
                return True
        except Exception:
            pass

    await page.screenshot(path="screenshot_02_after_nav.png")
    return False

async def apply_for_shifts(page, applied):
    count = 0
    await page.wait_for_timeout(2000)

    apply_btns = await page.query_selector_all('button:has-text("Apply")')
    log(f"Found {len(apply_btns)} Apply button(s)")

    if not apply_btns:
        log("No Apply buttons found")
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
            await page.wait_for_timeout(3000)
            await page.screenshot(path=f"screenshot_03_modal_{i}.png")

            confirmed = False
            for confirm_sel in [
                '.modal button:has-text("Apply")',
                '[role="dialog"] button:has-text("Apply")',
                'dialog button:has-text("Apply")',
                '.modal-footer button:has-text("Apply")',
                'button.btn-success',
                'button.btn-primary',
            ]:
                try:
                    mb = await page.wait_for_selector(confirm_sel, timeout=3000)
                    if mb and await mb.is_visible():
                        await mb.click()
                        await page.wait_for_timeout(3000)
                        confirmed = True
                        break
                except Exception:
                    continue

            if not confirmed:
                confirmed = await page.evaluate("""
                    () => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            if (b.textContent.trim() === 'Apply' && b.offsetParent !== null) {
                                b.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if confirmed:
                    await page.wait_for_timeout(2000)

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
            ok = await go_to_open_shifts(page)
            if ok:
                n = await apply_for_shifts(page, applied)
                if n:
                    log(f"SUCCESS - Applied for {n} new shift(s)!")
                else:
                    log("Run complete - no new shifts to apply for")
            else:
                log("WARNING - Could not reach Open Shifts page")
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
