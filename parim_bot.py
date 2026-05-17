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
    log(f"Opening {PARIM_URL} ...")
    await page.goto(PARIM_URL, wait_until="networkidle", timeout=40000)
    await page.wait_for_timeout(3000)
    await page.screenshot(path="screenshot_01_login_page.png")
    log("Login page loaded")

    email_sel = 'input[type="email"], input[name="email"], input[name="username"]'
    email_input = await page.wait_for_selector(email_sel, timeout=15000)
    await email_input.fill(EMAIL)
    log("Email entered")

    next_btn = await page.query_selector(
        'button:has-text("Next"), button:has-text("Continue"), input[value="Next"]'
    )
    if next_btn:
        log("Two-step login - clicking Next...")
        await next_btn.click()
        await page.wait_for_timeout(3000)

        team_sel = 'li[class*="team"], div[class*="team"], .team-item, li:has-text("Sword"), div:has-text("swordsecurity")'
        try:
            team_btn = await page.wait_for_selector(team_sel, timeout=5000)
            if team_btn:
                log("Team found - clicking...")
                await team_btn.click()
                await page.wait_for_timeout(3000)
        except Exception:
            try:
                first_item = await page.query_selector('li, .list-item, [role="listitem"]')
                if first_item:
                    await first_item.click()
                    await page.wait_for_timeout(3000)
            except Exception:
                pass
    else:
        await email_input.press("Tab")
        await page.wait_for_timeout(1000)

    pw_input = None
    for sel in ['input[type="password"]', 'input[name="password"]', 'input[autocomplete="current-password"]']:
        try:
            pw_input = await page.wait_for_selector(sel, timeout=8000)
            if pw_input:
                log("Password field found")
                break
        except Exception:
            continue

    if not pw_input:
        await page.screenshot(path="screenshot_error_no_password.png")
        raise Exception("Could not find password field")

    await pw_input.fill(PASSWORD)
    log("Password entered")

    btn = await page.query_selector(
        'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in"), button:has-text("Login")'
    )
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(3000)
    await page.screenshot(path="screenshot_02_after_login.png")
    log("Login complete!")

async def go_to_open_shifts(page):
    log("Navigating to Open Shifts...")

    base = PARIM_URL.rstrip("/")
    direct_urls = [
        base + "/open-shifts",
        base + "/shifts/open",
        base + "/employee/open-shifts",
    ]
    for url in direct_urls:
        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)
            content = await page.content()
            if "open" in page.url.lower() or "shift" in page.url.lower():
                await page.screenshot(path="screenshot_03_open_shifts.png")
                log(f"Navigated to Open Shifts: {page.url}")
                return True
        except Exception:
            pass

    sidebar_sels = [
        'a:has-text("Open Shifts")',
        'nav a:has-text("Open")',
        'aside a:has-text("Open")',
        'li a:has-text("Open Shifts")',
        '[href*="open"]',
    ]
    for sel in sidebar_sels:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=12000)
                await page.wait_for_timeout(2000)
                await page.screenshot(path="screenshot_03_open_shifts.png")
                log(f"Clicked sidebar Open Shifts: {page.url}")
                return True
        except Exception:
            pass

    await page.screenshot(path="screenshot_03_open_shifts.png")
    log("Could not navigate to Open Shifts page")
    return False

async def apply_for_shifts(page, applied):
    count = 0
    await page.wait_for_timeout(2000)

    rows = await page.query_selector_all("tr, .shift-row, [class*='shift-item'], [class*='row']")
    log(f"Found {len(rows)} rows on page")

    apply_btns = await page.query_selector_all('button:has-text("Apply")')
    log(f"Found {len(apply_btns)} Apply button(s)")

    if not apply_btns:
        await page.screenshot(path="screenshot_04_no_shifts.png")
        log("No Apply buttons found - no available shifts")
        return 0

    for i, btn in enumerate(apply_btns):
        try:
            is_visible = await btn.is_visible()
            is_enabled = await btn.is_enabled()
            if not is_visible or not is_enabled:
                continue

            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=row]') || el.closest('[class*=shift]') || el.parentElement.parentElement"
                )
                text = (await row.inner_text()).strip()
            except Exception:
                text = f"shift_{i}"

            shift_id = text[:200]
            if shift_id in applied:
                log(f"Already applied - skipping shift {i+1}")
                continue

            log(f"Clicking Apply for shift {i+1}: {text[:60]}...")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(2000)
            await page.screenshot(path=f"screenshot_05_modal_{i}.png")

            modal_apply = await page.query_selector(
                '.modal button:has-text("Apply"), '
                'dialog button:has-text("Apply"), '
                '[role="dialog"] button:has-text("Apply"), '
                '.modal-footer button:has-text("Apply"), '
                'button.btn-success:has-text("Apply"), '
                'button.btn-primary:has-text("Apply")'
            )
            if modal_apply and await modal_apply.is_visible():
                log("Confirmation modal found - clicking Apply...")
                await modal_apply.click()
                await page.wait_for_timeout(2000)
                log("Applied successfully!")
                applied.add(shift_id)
                save_applied(applied)
                count += 1
            else:
                visible_btns = await page.query_selector_all('button:has-text("Apply")')
                for vbtn in visible_btns:
                    if await vbtn.is_visible():
                        log("Clicking visible Apply button in modal...")
                        await vbtn.click()
                        await page.wait_for_timeout(2000)
                        applied.add(shift_id)
                        save_applied(applied)
                        count += 1
                        break

        except Exception as e:
            log(f"Error applying for shift {i+1}: {e}")
            await page.screenshot(path=f"screenshot_error_shift_{i}.png")

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
                log("Could not reach Open Shifts page")
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
