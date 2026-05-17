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
        await page.screenshot(path="screenshot_02_after_next.png")

        team_btn = await page.query_selector(
            'li, .team-item, [class*="team"], [class*="Team"], div[role="button"]'
        )
        if team_btn:
            log("Team selection found - clicking team...")
            await team_btn.click()
            await page.wait_for_timeout(3000)
            await page.screenshot(path="screenshot_03_after_team.png")
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
        raise Exception("Could not find password field - check screenshots in Artifacts")

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
    await page.wait_for_timeout(2000)
    await page.screenshot(path="screenshot_04_after_login.png")
    log("Login complete!")

async def go_to_open_shifts(page):
    await page.screenshot(path="screenshot_05_dashboard.png")
    selectors = [
        'a:has-text("Open Shifts")',
        'a:has-text("Open shifts")',
        'a:has-text("Available shifts")',
        'a:has-text("Available Shifts")',
        'li:has-text("Open Shifts") a',
        'nav a[href*="open"]',
        'nav a[href*="shift"]',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_load_state("networkidle", timeout=12000)
                await page.screenshot(path="screenshot_06_shifts_page.png")
                log("On Open Shifts page")
                return True
        except Exception:
            pass

    base = "/".join(page.url.split("/")[:3])
    for path in ["/shifts/open", "/open-shifts", "/shifts", "/employee/shifts"]:
        try:
            await page.goto(base + path, wait_until="networkidle", timeout=12000)
            await page.screenshot(path="screenshot_06_shifts_page.png")
            log(f"Navigated to {base + path}")
            return True
        except Exception:
            pass

    log("Could not reach Open Shifts page")
    return False

async def apply_for_shifts(page, applied):
    count = 0
    apply_btns = await page.query_selector_all(
        'button:has-text("Apply"), a.btn:has-text("Apply"), .apply-btn, button.green:has-text("Apply")'
    )

    if not apply_btns:
        log("No open shifts right now")
        return 0

    log(f"Found {len(apply_btns)} open shift(s)!")

    for btn in apply_btns:
        try:
            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('li') || el.parentElement"
                )
                text = (await row.inner_text()).strip()
            except Exception:
                text = (await btn.inner_text()).strip()

            shift_id = text[:200]
            if shift_id in applied:
                log("Already applied - skipping")
                continue

            log("Applying for shift...")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_timeout(2000)

            for confirm_sel in [
                'button:has-text("Apply")',
                'button:has-text("Confirm")',
                'button:has-text("Yes")',
                '.modal button.btn-primary',
            ]:
                cb = await page.query_selector(confirm_sel)
                if cb and await cb.is_visible():
                    await cb.click()
                    await page.wait_for_timeout(2000)
                    break

            applied.add(shift_id)
            save_applied(applied)
            count += 1
            log("Applied successfully!")
            await page.wait_for_timeout(1000)

        except Exception as e:
            log(f"Could not apply: {e}")

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("PARIM_EMAIL or PARIM_PASSWORD not set!")
        sys.exit(1)

    log("PARiM Auto-Apply Bot - Cloud Edition - Starting")
    applied = load_applied()
    log(f"History: {len(applied)} previously-applied shifts loaded")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await login(page)
            ok = await go_to_open_shifts(page)
            if ok:
                n = await apply_for_shifts(page, applied)
                if n:
                    log(f"Applied for {n} new shift(s) this run!")
                else:
                    log("Run complete - no new shifts this time")
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
