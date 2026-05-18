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
        'input[type="email"], input[name="email"], input[name="username"]',
        timeout=15000
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

async def navigate_to_open_shifts(page):
    staff_url = PARIM_URL.rstrip("/") + "/staff"
    log(f"Loading staff page: {staff_url}")
    await page.goto(staff_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(4000)

    open_shifts_url = PARIM_URL.rstrip("/") + "/s/event/index"
    log(f"Navigating iframe to: {open_shifts_url}")
    await page.evaluate(f"""
        () => {{
            const iframe = document.getElementById('monolith-iframe');
            if (iframe) {{
                iframe.src = '{open_shifts_url}';
            }}
        }}
    """)

    log("Waiting 15 seconds for Open Shifts to load...")
    await page.wait_for_timeout(15000)
    await page.screenshot(path="screenshot_01_open_shifts.png")
    log("Open Shifts page ready")

async def get_apply_buttons(page):
    result = await page.evaluate("""
        () => {
            try {
                const iframe = document.getElementById('monolith-iframe');
                if (!iframe) return {error: 'no iframe', count: 0, shifts: []};
                const doc = iframe.contentDocument || iframe.contentWindow.document;
                if (!doc) return {error: 'no contentDocument', count: 0, shifts: []};

                const allBtns = Array.from(doc.querySelectorAll('button'));
                const applyBtns = allBtns.filter(b =>
                    b.textContent.trim() === 'Apply' && b.offsetParent !== null
                );

                const shifts = applyBtns.map((btn, i) => {
                    const row = btn.closest('tr') ||
                                btn.closest('[class*="row"]') ||
                                btn.parentElement?.parentElement;
                    return {
                        index: i,
                        text: (row ? row.innerText : btn.innerText).trim().substring(0, 200)
                    };
                });

                return {error: null, count: applyBtns.length, shifts: shifts};
            } catch(e) {
                return {error: e.message, count: 0, shifts: []};
            }
        }
    """)
    return result

async def click_apply_button(page, index):
    return await page.evaluate(f"""
        () => {{
            try {{
                const iframe = document.getElementById('monolith-iframe');
                const doc = iframe.contentDocument || iframe.contentWindow.document;
                const allBtns = Array.from(doc.querySelectorAll('button'));
                const applyBtns = allBtns.filter(b =>
                    b.textContent.trim() === 'Apply' && b.offsetParent !== null
                );
                if (applyBtns[{index}]) {{
                    applyBtns[{index}].click();
                    return 'clicked';
                }}
                return 'not found at index {index}';
            }} catch(e) {{
                return 'error: ' + e.message;
            }}
        }}
    """)

async def click_modal_apply(page):
    return await page.evaluate("""
        () => {
            try {
                const iframe = document.getElementById('monolith-iframe');
                const doc = iframe.contentDocument || iframe.contentWindow.document;

                const selectors = [
                    '.modal-footer .btn-success',
                    '.modal-footer button:last-child',
                    '.modal button.btn-success',
                    '.modal button.btn-primary',
                    '[class*="modal"] button.btn-success',
                ];

                for (const sel of selectors) {
                    const btn = doc.querySelector(sel);
                    if (btn && btn.offsetParent !== null) {
                        btn.click();
                        return 'clicked via ' + sel;
                    }
                }

                const allBtns = Array.from(doc.querySelectorAll('button'));
                const modal = doc.querySelector('.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]');
                if (modal) {
                    const modalBtns = Array.from(modal.querySelectorAll('button'));
                    const applyBtn = modalBtns.find(b => b.textContent.trim() === 'Apply');
                    if (applyBtn) {
                        applyBtn.click();
                        return 'clicked via modal search';
                    }
                }

                const visibleApply = allBtns.find(b =>
                    b.textContent.trim() === 'Apply' && b.offsetParent !== null
                );
                if (visibleApply) {
                    visibleApply.click();
                    return 'clicked via visible button';
                }

                return 'no modal apply button found';
            } catch(e) {
                return 'error: ' + e.message;
            }
        }
    """)

async def apply_for_shifts(page, applied):
    count = 0

    info = await get_apply_buttons(page)
    log(f"Iframe status: error={info.get('error')}, Apply buttons={info.get('count')}")

    if info.get('count', 0) == 0:
        log("No Apply buttons found - no new shifts available")
        return 0

    shifts = info.get('shifts', [])
    log(f"Shifts to apply: {len(shifts)}")

    for i, shift in enumerate(shifts):
        shift_id = shift['text']
        shift_idx = shift['index']

        if shift_id in applied:
            log(f"Already applied to this shift - skipping")
            continue

        log(f"Applying for shift {i+1}: {shift_id[:80]}...")

        result = await click_apply_button(page, shift_idx)
        log(f"Click result: {result}")

        if result != 'clicked':
            log(f"Could not click Apply button")
            continue

        await page.wait_for_timeout(3000)
        await page.screenshot(path=f"screenshot_0{i+2}_after_click.png")

        confirm_result = await click_modal_apply(page)
        log(f"Modal confirm result: {confirm_result}")
        await page.wait_for_timeout(3000)

        if 'clicked' in confirm_result:
            applied.add(shift_id)
            save_applied(applied)
            count += 1
            log(f"SUCCESS! Applied for shift {i+1}!")
            await page.screenshot(path=f"screenshot_success_{i+1}.png")
        else:
            log(f"Modal confirm failed: {confirm_result}")

        await page.wait_for_timeout(2000)

    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("PARIM_EMAIL or PARIM_PASSWORD not set!")
        sys.exit(1)

    log("PARiM Auto-Apply Bot - Starting")
    applied = load_applied()
    log(f"History: {len(applied)} previously applied shifts")

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
            await navigate_to_open_shifts(page)
            n = await apply_for_shifts(page, applied)
            if n:
                log(f"SUCCESS - Applied for {n} new shift(s) this run!")
            else:
                log("Run complete - no new shifts to apply for")
        except Exception as e:
            log(f"Error: {e}")
            try:
                await page.screenshot(path="screenshot_error.png")
            except Exception:
                pass
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
