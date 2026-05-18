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
    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    await page.wait_for_load_state("load", timeout=30000)
    await page.wait_for_timeout(5000)
    log(f"Logged in! URL={page.url}")

async def find_apply_elements(frame):
    """Find Apply elements - could be <a>, <button>, or <input>"""
    # Log what selectors find
    results = await frame.evaluate("""
        () => {
            const selectors = [
                'button:contains("Apply")',
                'a.btn',
                '.btn-success',
                '.btn-primary',
                'a[href*="apply"]',
                'a[href*="application"]',
                'input[value="Apply"]',
            ];
            const allElements = Array.from(document.querySelectorAll('a, button, input[type=button], input[type=submit]'));
            const withApply = allElements.filter(el => {
                const text = el.textContent || el.value || '';
                return text.trim().toLowerCase() === 'apply';
            });
            return {
                totalLinks: document.querySelectorAll('a').length,
                totalButtons: document.querySelectorAll('button').length,
                applyElements: withApply.map(el => ({
                    tag: el.tagName,
                    text: el.textContent || el.value,
                    href: el.href || '',
                    classes: el.className,
                    visible: el.offsetParent !== null
                }))
            };
        }
    """)
    return results

async def click_apply_and_confirm(frame, page, i, text, applied):
    """Click an Apply element and confirm the modal"""
    # Click the Apply element
    clicked = await frame.evaluate(f"""
        () => {{
            const allElements = Array.from(document.querySelectorAll('a, button, input[type=button], input[type=submit]'));
            const applyEls = allElements.filter(el => {{
                const txt = el.textContent || el.value || '';
                return txt.trim().toLowerCase() === 'apply' && el.offsetParent;
            }});
            if (applyEls[{i}]) {{
                applyEls[{i}].click();
                return 'clicked ' + applyEls[{i}].tagName + ' ' + applyEls[{i}].className;
            }}
            return 'not found at index {i}';
        }}
    """)
    log(f"  Click result: {clicked}")

    if 'clicked' not in clicked:
        return False

    await asyncio.sleep(3)
    await page.screenshot(path=f"screenshot_modal_{i}.png")

    # Confirm the modal - try multiple selectors
    confirmed = await frame.evaluate("""
        () => {
            // Look for modal confirm button
            const modalSelectors = [
                '.modal-footer .btn-success',
                '.modal-footer a.btn-success',
                '.modal-footer button.btn-success',
                '.modal .btn-success',
                '.modal a:last-child',
                '.modal button:last-child',
                '[data-dismiss="modal"] ~ a',
                '.modal-footer a:last-child',
            ];
            for (const sel of modalSelectors) {
                const btn = document.querySelector(sel);
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    return 'confirmed via ' + sel;
                }
            }
            // Fallback: find any visible element with Apply text in modal area
            const modal = document.querySelector('.modal.in, .modal[style*="block"], .modal[aria-hidden="false"]');
            if (modal) {
                const els = Array.from(modal.querySelectorAll('a, button'));
                const applyEl = els.find(el => (el.textContent || '').trim().toLowerCase() === 'apply' && el.offsetParent);
                if (applyEl) { applyEl.click(); return 'confirmed via modal search'; }
            }
            // Last resort: any visible Apply element
            const all = Array.from(document.querySelectorAll('a, button'));
            const visible = all.find(el => (el.textContent || '').trim().toLowerCase() === 'apply' && el.offsetParent);
            if (visible) { visible.click(); return 'confirmed via visible'; }
            return 'not found';
        }
    """)
    log(f"  Confirm result: {confirmed}")

    await asyncio.sleep(3)
    if 'confirmed' in confirmed:
        applied.add(text)
        save_applied(applied)
        await page.screenshot(path=f"screenshot_done_{i}.png")
        return True
    return False

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

            # Already on /staff after login - just wait
            if "/staff" not in page.url:
                await page.goto(PARIM_URL + "/staff", wait_until="load", timeout=30000)
            await page.wait_for_timeout(6000)
            log(f"Staff page. Frames: {[f.url for f in page.frames]}")

            # Find monolith frame
            mf = None
            for f in page.frames:
                if "/s/" in f.url:
                    mf = f
                    break
            if not mf and len(page.frames) > 1:
                mf = page.frames[1]
            log(f"Monolith frame: {mf.url if mf else 'NOT FOUND'}")

            if not mf:
                raise Exception("No monolith frame found")

            # Navigate frame to Open Shifts
            log("Navigating frame to Open Shifts...")
            await mf.goto(PARIM_URL + "/s/event/index", wait_until="load", timeout=20000)
            await asyncio.sleep(8)  # Wait for AJAX/SPA to render
            log(f"Frame URL: {mf.url}")
            await page.screenshot(path="screenshot_01_open_shifts.png")

            # Diagnose what Apply elements exist
            info = await find_apply_elements(mf)
            log(f"Links: {info['totalLinks']}, Buttons: {info['totalButtons']}")
            log(f"Apply elements found: {info['applyElements']}")

            total = 0
            apply_els = [el for el in info['applyElements'] if el.get('visible')]
            log(f"Visible Apply elements: {len(apply_els)}")

            for i, el_info in enumerate(apply_els):
                shift_text = f"apply_{i}_{el_info.get('href', '')}"
                if shift_text in applied:
                    log(f"Shift {i+1} already applied")
                    continue
                log(f"Applying shift {i+1}: tag={el_info['tag']} class={el_info['classes'][:40]}")
                success = await click_apply_and_confirm(mf, page, i, shift_text, applied)
                if success:
                    total += 1
                    log(f"SUCCESS! Applied shift {i+1}!")
                # Re-query after each apply since DOM changes
                await asyncio.sleep(2)
                info = await find_apply_elements(mf)
                apply_els = [el for el in info['applyElements'] if el.get('visible')]

            log(f"=== Done. Applied for {total} shift(s) ===")

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
