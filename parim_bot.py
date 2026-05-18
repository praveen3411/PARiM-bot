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

            # Already on /staff after login
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

            # Navigate to Open Shifts page
            await mf.goto(PARIM_URL + "/s/event/index", wait_until="load", timeout=20000)
            await asyncio.sleep(8)
            log(f"Open Shifts loaded: {mf.url}")
            await page.screenshot(path="screenshot_01_open_shifts.png")

            total = 0

            # Keep applying until no more available shifts
            for attempt in range(30):
                # Find ALL visible Apply buttons using exact class from DevTools
                # Apply button HTML: <a class="apply btn btn-xs btn-success fr" href="/s/event/#">Apply</a>
                apply_info = await mf.evaluate("""
                    () => {
                        const btns = Array.from(document.querySelectorAll('a.apply'));
                        const visible = btns.filter(a => a.offsetParent !== null);
                        return {
                            count: visible.length,
                            shifts: visible.map((a, i) => {
                                const row = a.closest('.venue-wrap') ||
                                            a.closest('.event-list-shift-row') ||
                                            a.closest('.row') ||
                                            a.parentElement;
                                const shiftId = a.getAttribute('data-shift-id') ||
                                               row?.getAttribute('data-shift-id') ||
                                               a.getAttribute('data-team-id') + '_' + i;
                                return {
                                    index: i,
                                    shiftId: shiftId || ('shift_' + i),
                                    label: row ? row.innerText.trim().substring(0, 80) : ('shift_' + i)
                                };
                            })
                        };
                    }
                """)

                available = apply_info.get('shifts', [])
                log(f"Attempt {attempt+1}: {len(available)} available shift(s)")

                if not available:
                    log("No more available shifts")
                    break

                # Apply for the first not-yet-applied shift
                applied_one = False
                for shift in available:
                    sid = shift['shiftId']
                    if sid in applied:
                        log(f"Already applied: {sid}")
                        continue

                    log(f"Applying: {shift['label'][:60]}")

                    # Click the Apply button (a.apply)
                    click_result = await mf.evaluate("""
                        () => {
                            const btn = document.querySelector('a.apply');
                            if (btn && btn.offsetParent) {
                                btn.click();
                                return 'clicked: ' + btn.className;
                            }
                            return 'not found';
                        }
                    """)
                    log(f"Click: {click_result}")

                    if 'clicked' not in click_result:
                        continue

                    await asyncio.sleep(3)
                    await page.screenshot(path=f"screenshot_modal_{attempt}.png")

                    # Confirm via modal OK button
                    # Modal HTML: <a class="btn btn-success fr" id="ok-btn" href="#">Apply</a>
                    confirm_result = await mf.evaluate("""
                        () => {
                            // Exact id from DevTools
                            const okBtn = document.getElementById('ok-btn');
                            if (okBtn && okBtn.offsetParent !== null) {
                                okBtn.click();
                                return 'confirmed via #ok-btn';
                            }
                            // Fallback: any visible btn-success not in the shift list
                            const fallback = document.querySelector('.ui-dialog-buttons .btn-success, .modal-footer .btn-success');
                            if (fallback && fallback.offsetParent !== null) {
                                fallback.click();
                                return 'confirmed via dialog buttons';
                            }
                            return 'modal not found';
                        }
                    """)
                    log(f"Confirm: {confirm_result}")
                    await asyncio.sleep(4)

                    if 'confirmed' in confirm_result:
                        applied.add(sid)
                        save_applied(applied)
                        total += 1
                        applied_one = True
                        log(f"SUCCESS! Applied for: {shift['label'][:60]}")
                        await page.screenshot(path=f"screenshot_done_{total}.png")
                        break
                    else:
                        log("Modal not confirmed - trying next shift")

                if not applied_one:
                    log("Could not apply for any remaining shift - stopping")
                    break

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
