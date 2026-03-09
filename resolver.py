"""
Link Resolver – Playwright-based redirect chain navigator.

Navigates through rinku.pro / 7mb.io / Fly Inc shortener pages,
bypasses countdown timers and focus-detection tricks, and returns
the final destination URL.
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional

from playwright.async_api import async_playwright, Page, BrowserContext

# ---------------------------------------------------------------------------
# Result data class
# ---------------------------------------------------------------------------

@dataclass
class ResolveResult:
    success: bool
    final_url: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Known shortener / intermediate domains
# ---------------------------------------------------------------------------

SHORTENER_DOMAINS = [
    "rinku.pro",
    "7mb.io",
    "flyinc.xyz",
    "fly-link.io",
    "fly-url.com",
    "shrinkforearn.in",
    "earnfly.io",
    "adslift.xyz",
]

# Patterns that indicate an intermediate "continue" page
CONTINUE_BUTTON_SELECTORS = [
    "a#btn-main",
    "a.btn-main",
    "a.get-link",
    "a#get-link",
    'a[href*="continue"]',
    "button.continue",
    'a:has-text("Get Link")',
    'a:has-text("Continue")',
    'a:has-text("Click here")',
    'a:has-text("Go to Link")',
    'button:has-text("Continue")',
    'button:has-text("Get Link")',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_shortener_url(url: str) -> bool:
    """Return True if *url* belongs to a known shortener domain."""
    for domain in SHORTENER_DOMAINS:
        if domain in url:
            return True
    return False


async def _has_cloudflare_challenge(page: Page) -> bool:
    """Return True if the page contains a Cloudflare Turnstile challenge."""
    try:
        return await page.evaluate("""() => {
            // Check for Turnstile iframe
            if (document.querySelector('iframe[src*="challenges.cloudflare.com"]'))
                return true;
            // Check for Turnstile container
            if (document.querySelector('.cf-turnstile, [data-sitekey]'))
                return true;
            // Check for challenge text
            const body = document.body?.innerText || '';
            if (body.includes('Verify you are human') || body.includes('Vérifiez que vous êtes humain'))
                return true;
            return false;
        }""")
    except Exception:
        return False


async def _wait_for_cloudflare(page: Page, log, timeout: float = 30) -> bool:
    """Wait for a Cloudflare Turnstile challenge to auto-resolve.

    Returns True if the challenge was cleared (page navigated away).
    """
    await log("☁️ Cloudflare Turnstile detected, waiting for auto-resolution…")
    start = time.monotonic()
    initial_url = page.url
    while time.monotonic() - start < timeout:
        await asyncio.sleep(1.5)
        # If the page navigated away, challenge was cleared
        if page.url != initial_url:
            await log("☁️ Cloudflare challenge cleared!")
            return True
        # Check if the Turnstile widget disappeared
        still_present = await _has_cloudflare_challenge(page)
        if not still_present:
            await log("☁️ Cloudflare challenge cleared!")
            return True
    await log("⚠ Cloudflare challenge did not auto-resolve")
    return False


async def _inject_timer_bypass(page: Page) -> None:
    """Inject JS that speeds up countdown timers and disables focus checks."""
    await page.evaluate("""() => {
        // Override setInterval so timers tick every 1ms
        const _origSetInterval = window.setInterval;
        window.setInterval = (fn, delay, ...args) =>
            _origSetInterval(fn, 1, ...args);

        // Override setTimeout similarly
        const _origSetTimeout = window.setTimeout;
        window.setTimeout = (fn, delay, ...args) =>
            _origSetTimeout(fn, 1, ...args);

        // Fake document visibility – always "visible"
        Object.defineProperty(document, 'hidden', {value: false, writable: false});
        Object.defineProperty(document, 'visibilityState', {value: 'visible', writable: false});

        // Suppress visibilitychange / blur events that pause timers
        document.addEventListener('visibilitychange', e => e.stopImmediatePropagation(), true);
        window.addEventListener('blur', e => e.stopImmediatePropagation(), true);
        window.addEventListener('focus', e => e.stopImmediatePropagation(), true);
    }""")


async def _try_click_continue(page: Page) -> bool:
    """Try to find and click a continue / get-link button. Returns True if clicked."""
    for selector in CONTINUE_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=300):
                await btn.click(timeout=2000)
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

async def resolve_link(
    url: str,
    callback: Optional[Callable[[str], Awaitable[None]]] = None,
    timeout: float = 60,
    max_retries: int = 2,
) -> ResolveResult:
    """
    Navigate through a shortener redirect chain and return the final URL.

    Parameters
    ----------
    url : str
        The shortener URL to resolve.
    callback : async callable, optional
        An ``async def callback(message: str)`` invoked with progress updates.
    timeout : float
        Maximum seconds before giving up (default 60).
    max_retries : int
        How many times to retry on failure (default 2).
    """

    async def log(msg: str) -> None:
        if callback:
            await callback(msg)

    start = time.monotonic()

    for attempt in range(1, max_retries + 1):
        try:
            return await _resolve_once(url, log, timeout, attempt, max_retries)
        except Exception as exc:
            elapsed = round(time.monotonic() - start, 1)
            if attempt < max_retries:
                await log(f"⚠ Attempt {attempt} failed ({exc}), retrying…")
            else:
                await log(f"❌ All {max_retries} attempts failed.")
                return ResolveResult(
                    success=False,
                    final_url=None,
                    elapsed_seconds=elapsed,
                    error=str(exc),
                )

    # Should never reach here, but just in case
    return ResolveResult(success=False, error="Unknown error")


_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_WEBDRIVER_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


async def _launch_browser(pw, headless: bool, log):
    """Launch a browser and create a stealth context + page."""
    browser = await pw.chromium.launch(
        headless=headless,
        args=_STEALTH_ARGS,
    )

    context: BrowserContext = await browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 720},
        java_script_enabled=True,
    )

    # Block heavy resources to speed things up
    await context.route(
        "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot}",
        lambda route: route.abort(),
    )

    page = await context.new_page()

    # Remove navigator.webdriver flag to avoid bot detection
    await page.add_init_script(_WEBDRIVER_INIT_SCRIPT)

    # Close popup windows opened by ad scripts
    context.on(
        "page",
        lambda new_page: asyncio.ensure_future(_close_popup(new_page, log)),
    )

    return browser, context, page


async def _bypass_cloudflare_headed(pw, url: str, log) -> Optional[str]:
    """Re-launch in headed (visible) mode to pass Cloudflare Turnstile.

    Returns the post-challenge URL if successful, None otherwise.
    """
    await log("☁️ Headless blocked by Cloudflare – retrying in headed mode…")
    browser, context, page = await _launch_browser(pw, headless=False, log=log)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        cleared = await _wait_for_cloudflare(page, log, timeout=30)
        if cleared:
            # Grab cookies so we can transfer them to headless session
            final_url = page.url
            return final_url
        return None
    finally:
        await browser.close()


async def _resolve_once(
    url: str,
    log: Callable[[str], Awaitable[None]],
    timeout: float,
    attempt: int,
    max_retries: int,
) -> ResolveResult:
    start = time.monotonic()
    await log(f"🚀 Starting resolution (attempt {attempt}/{max_retries})…")

    async with async_playwright() as pw:
        browser, context, page = await _launch_browser(pw, headless=True, log=log)

        await log(f"🌐 Navigating to {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            await log(f"⚠ Initial navigation issue: {e}")

        # Check for Cloudflare challenge before injecting timer bypass
        # (timer override breaks Turnstile scripts)
        if await _has_cloudflare_challenge(page):
            cleared = await _wait_for_cloudflare(page, log, timeout=10)
            if not cleared:
                # Headless can't pass Turnstile – switch to headed mode
                await browser.close()
                post_cf_url = await _bypass_cloudflare_headed(pw, url, log)
                if post_cf_url:
                    # Re-launch headless and continue from the post-challenge URL
                    url = post_cf_url
                    await log(f"☁️ Resuming headless from {url}")
                browser, context, page = await _launch_browser(
                    pw, headless=True, log=log
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        await _inject_timer_bypass(page)

        deadline = time.monotonic() + timeout
        last_url = page.url
        idle_rounds = 0

        while time.monotonic() < deadline:
            current_url = page.url
            await log(f"📍 Current URL: {current_url}")

            # If we've left all shortener domains, we're done
            if not _is_shortener_url(current_url) and current_url != url:
                elapsed = round(time.monotonic() - start, 1)
                await log(f"✅ Resolved to final URL in {elapsed}s")
                await browser.close()
                return ResolveResult(
                    success=True,
                    final_url=current_url,
                    elapsed_seconds=elapsed,
                )

            # Check for Cloudflare challenge before proceeding
            if await _has_cloudflare_challenge(page):
                cleared = await _wait_for_cloudflare(page, log, timeout=10)
                if not cleared:
                    # Switch to headed mode for this challenge
                    current_cf_url = page.url
                    await browser.close()
                    post_cf_url = await _bypass_cloudflare_headed(
                        pw, current_cf_url, log
                    )
                    if post_cf_url:
                        current_cf_url = post_cf_url
                    browser, context, page = await _launch_browser(
                        pw, headless=True, log=log
                    )
                    await page.goto(
                        current_cf_url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                idle_rounds = 0
                continue

            # Re-inject timer bypass on each page (safe now – no Cloudflare)
            try:
                await _inject_timer_bypass(page)
            except Exception:
                pass

            # Try clicking continue buttons
            clicked = await _try_click_continue(page)
            if clicked:
                await log("🖱️ Clicked continue button")
                idle_rounds = 0
                # Wait for potential navigation
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)
                continue

            # Check if URL changed without a click
            if current_url != last_url:
                await log(f"🔄 Redirect detected")
                last_url = current_url
                idle_rounds = 0
                await asyncio.sleep(0.5)
                continue

            idle_rounds += 1

            # If idle for too long, the page might be stuck
            if idle_rounds > 20:
                await log("⚠ Page appears stuck, attempting reload")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=10000)
                    await _inject_timer_bypass(page)
                except Exception:
                    pass
                idle_rounds = 0

            await asyncio.sleep(1)

        # Timed out
        elapsed = round(time.monotonic() - start, 1)
        final = page.url
        await browser.close()

        if not _is_shortener_url(final) and final != url:
            await log(f"✅ Resolved (at timeout boundary) in {elapsed}s")
            return ResolveResult(success=True, final_url=final, elapsed_seconds=elapsed)

        await log(f"❌ Timed out after {elapsed}s")
        return ResolveResult(
            success=False,
            final_url=final if final != url else None,
            elapsed_seconds=elapsed,
            error=f"Timed out after {elapsed}s",
        )


async def _close_popup(page: Page, log: Callable[[str], Awaitable[None]]) -> None:
    """Close popup windows that ad scripts open."""
    try:
        await log(f"🚫 Closing popup: {page.url}")
        await page.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _cli_main(url: str) -> None:
    async def printer(msg: str) -> None:
        print(msg)

    result = await resolve_link(url, callback=printer)
    if result.success:
        print(f"\nFinal URL: {result.final_url}")
    else:
        print(f"\nFailed: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python resolver.py <URL>")
        sys.exit(1)
    asyncio.run(_cli_main(sys.argv[1]))
