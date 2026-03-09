"""Tests for the resolver module."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from resolver import (
    ResolveResult,
    resolve_link,
    _is_shortener_url,
    _has_cloudflare_challenge,
    _wait_for_cloudflare,
    SHORTENER_DOMAINS,
    CONTINUE_BUTTON_SELECTORS,
)


# ---------------------------------------------------------------------------
# ResolveResult tests
# ---------------------------------------------------------------------------

class TestResolveResult:
    def test_success_result(self):
        r = ResolveResult(success=True, final_url="https://example.com", elapsed_seconds=2.5)
        assert r.success is True
        assert r.final_url == "https://example.com"
        assert r.elapsed_seconds == 2.5
        assert r.error is None

    def test_failure_result(self):
        r = ResolveResult(success=False, error="Timed out")
        assert r.success is False
        assert r.final_url is None
        assert r.error == "Timed out"

    def test_defaults(self):
        r = ResolveResult(success=False)
        assert r.final_url is None
        assert r.elapsed_seconds is None
        assert r.error is None


# ---------------------------------------------------------------------------
# _is_shortener_url tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cloudflare detection tests
# ---------------------------------------------------------------------------

class TestCloudflareDetection:
    @pytest.mark.asyncio
    async def test_has_cloudflare_challenge_detects_turnstile(self):
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=True)
        assert await _has_cloudflare_challenge(mock_page) is True

    @pytest.mark.asyncio
    async def test_has_cloudflare_challenge_returns_false_when_absent(self):
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=False)
        assert await _has_cloudflare_challenge(mock_page) is False

    @pytest.mark.asyncio
    async def test_has_cloudflare_challenge_handles_exception(self):
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("page closed"))
        assert await _has_cloudflare_challenge(mock_page) is False

    @pytest.mark.asyncio
    async def test_wait_for_cloudflare_clears_on_url_change(self):
        mock_page = AsyncMock()
        mock_page.url = "https://adslift.xyz/challenge"
        log = AsyncMock()

        # After first sleep, URL changes
        call_count = 0
        original_url = mock_page.url

        def url_getter():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return "https://adslift.xyz/land/next"
            return original_url

        type(mock_page).url = property(lambda self: url_getter())

        result = await _wait_for_cloudflare(mock_page, log, timeout=5)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_cloudflare_clears_on_widget_disappear(self):
        mock_page = AsyncMock()
        mock_page.url = "https://adslift.xyz/challenge"
        # evaluate returns False (widget gone)
        mock_page.evaluate = AsyncMock(return_value=False)
        log = AsyncMock()

        result = await _wait_for_cloudflare(mock_page, log, timeout=5)
        assert result is True

    def test_adslift_is_shortener(self):
        assert _is_shortener_url("https://adslift.xyz/rinku/land/") is True


class TestIsShortenerUrl:
    def test_known_domains(self):
        assert _is_shortener_url("https://rinku.pro/abc") is True
        assert _is_shortener_url("https://7mb.io/xyz") is True
        assert _is_shortener_url("https://flyinc.xyz/link") is True

    def test_non_shortener(self):
        assert _is_shortener_url("https://example.com") is False
        assert _is_shortener_url("https://google.com") is False

    def test_shortener_in_path(self):
        # Domain check is substring-based, so this is expected
        assert _is_shortener_url("https://example.com/rinku.pro") is True


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_shortener_domains_not_empty(self):
        assert len(SHORTENER_DOMAINS) > 0

    def test_continue_button_selectors_not_empty(self):
        assert len(CONTINUE_BUTTON_SELECTORS) > 0

    def test_known_domains_present(self):
        assert "rinku.pro" in SHORTENER_DOMAINS
        assert "7mb.io" in SHORTENER_DOMAINS
        assert "adslift.xyz" in SHORTENER_DOMAINS


# ---------------------------------------------------------------------------
# resolve_link tests (with mocked Playwright)
# ---------------------------------------------------------------------------

class TestResolveLink:
    @pytest.mark.asyncio
    async def test_callback_is_called(self):
        """Verify that the callback receives progress messages."""
        messages = []

        async def cb(msg):
            messages.append(msg)

        # Mock playwright to simulate a quick resolution
        with patch("resolver.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_page = AsyncMock()

            mock_page.url = "https://example.com/final"
            mock_page.goto = AsyncMock()
            mock_page.evaluate = AsyncMock()

            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.route = AsyncMock()
            mock_context.on = MagicMock()

            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_browser.close = AsyncMock()

            mock_pw_instance = AsyncMock()
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await resolve_link("https://rinku.pro/test", callback=cb)

        assert result.success is True
        assert result.final_url == "https://example.com/final"
        assert len(messages) > 0
        # Should contain the start message
        assert any("Starting" in m for m in messages)

    @pytest.mark.asyncio
    async def test_no_callback(self):
        """Resolver should work without a callback."""
        with patch("resolver.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_page = AsyncMock()

            mock_page.url = "https://example.com/video"
            mock_page.goto = AsyncMock()
            mock_page.evaluate = AsyncMock()

            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.route = AsyncMock()
            mock_context.on = MagicMock()

            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_browser.close = AsyncMock()

            mock_pw_instance = AsyncMock()
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await resolve_link("https://rinku.pro/test")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_retries_on_exception(self):
        """Resolver retries when an exception occurs."""
        call_count = 0

        async def fake_resolve_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("browser crashed")

        messages = []

        async def cb(msg):
            messages.append(msg)

        with patch("resolver._resolve_once", side_effect=fake_resolve_once):
            result = await resolve_link("https://rinku.pro/test", callback=cb, max_retries=3)

        assert result.success is False
        assert "browser crashed" in result.error
        assert call_count == 3
        assert any("retrying" in m.lower() for m in messages)
