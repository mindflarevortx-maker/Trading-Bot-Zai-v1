"""
Quotex API Client Wrapper for Trading Bot Zai v1.2.

Provides a clean async interface for:
  - Authentication & connection (3-tier fallback)
  - Fetching deep historical candle data (30 days, 1-min)
  - Fetching recent candle updates for cache gap-fill
"""

import asyncio
import json
import logging
import time
from typing import Optional

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, QUOTEX_LANG,
    ACCOUNT_MODE, CANDLE_PERIOD, HISTORY_SECONDS,
    PROXY_HTTP, PROXY_HTTPS, SESSION_FILE,
    FETCH_BATCH_TIMEOUT, FETCH_MAX_WORKERS,
)

logger = logging.getLogger("quotex_client")


def _patch_login_host(host: str):
    """Patch Login class base_url class attributes for custom broker domain."""
    for module_path in ("pyquotex.network.login", "quotex.network.login"):
        try:
            import importlib
            login_module = importlib.import_module(module_path)
            LoginClass = getattr(login_module, "Login", None)
            if LoginClass is not None:
                LoginClass.base_url = host
                LoginClass.https_base_url = f"https://{host}"
                logger.info(f"Patched Login.base_url → {host}")
                return True
        except ImportError:
            continue
    logger.warning("Could not patch Login class base_url.")
    return False


def _patch_ssl_verification():
    """Patch Browser class to disable strict SSL verification."""
    for module_path in ("pyquotex.network.navigator", "quotex.network.navigator"):
        try:
            import importlib
            nav_module = importlib.import_module(module_path)
            BrowserClass = getattr(nav_module, "Browser", None)
            if BrowserClass is not None and not getattr(BrowserClass, "_ssl_patched", False):
                import httpx as _httpx
                original_init = BrowserClass.__init__

                def patched_init(self, *args, **kwargs):
                    try:
                        original_init(self, *args, **kwargs)
                    except Exception:
                        self.response = None
                        self.default_headers = None
                        self.headers = {}
                    self._client = _httpx.AsyncClient(
                        verify=False, timeout=30.0, follow_redirects=True,
                        proxy=kwargs.get("proxy") if isinstance(kwargs.get("proxies"), str) else None,
                    )
                    try:
                        import ssl
                        self._ssl_context = ssl.create_default_context()
                        self._ssl_context.check_hostname = False
                        self._ssl_context.verify_mode = ssl.CERT_NONE
                    except Exception:
                        pass

                BrowserClass.__init__ = patched_init
                BrowserClass._ssl_patched = True
                logger.info("Patched Browser to disable SSL verification")
                return True
        except ImportError:
            continue
    return False


class QuotexClient:
    """High-level async client for Quotex broker."""

    def __init__(self):
        self.client = None
        self._connected = False
        self._proxies = None
        if PROXY_HTTPS:
            self._proxies = {"https": PROXY_HTTPS, "http": PROXY_HTTP or PROXY_HTTPS}

    async def connect(self) -> bool:
        """Connect to Quotex with 3-tier fallback."""
        try:
            from quotex.stable_api import Quotex
        except ImportError:
            try:
                from pyquotex.stable_api import Quotex
            except ImportError:
                logger.error("Neither 'quotex' nor 'pyquotex' package found.")
                return False

        _patch_login_host(QUOTEX_HOST)
        _patch_ssl_verification()
        self._clean_stale_session()

        # Tier 1: Direct login
        connected = await self._try_direct_login(Quotex)
        if connected:
            return True

        # Tier 2: Saved session
        connected = await self._try_saved_session(Quotex)
        if connected:
            return True

        # Tier 3: Browser login
        from bot.quotex_client import _extract_session_via_browser
        session_data = await _extract_session_via_browser(
            host=QUOTEX_HOST, email=QUOTEX_EMAIL,
            password=QUOTEX_PASSWORD, lang=QUOTEX_LANG,
        )
        if session_data and session_data.get("token") and session_data.get("cookies"):
            _save_session_file(session_data)
            connected = await self._try_with_session(Quotex, session_data)
            if connected:
                return True

        logger.error("All connection methods failed.")
        return False

    async def _try_direct_login(self, Quotex) -> bool:
        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL, password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST, lang=QUOTEX_LANG,
                asset_default="EURUSD_otc", period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )
            self.client.set_account_mode(ACCOUNT_MODE)
            logger.info(f"Connecting to {QUOTEX_HOST} as {QUOTEX_EMAIL}...")
            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected via direct login: {reason}")
                return True
            logger.warning(f"Direct login failed: {reason}")
            return False
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                logger.info("CloudFlare challenge detected (HTTP 403)")
            else:
                logger.warning(f"Direct login error: {e}")
            return False

    async def _try_saved_session(self, Quotex) -> bool:
        session_data = _load_session_file()
        if not session_data.get("token") or not session_data.get("cookies"):
            return False
        return await self._try_with_session(Quotex, session_data)

    async def _try_with_session(self, Quotex, session_data: dict) -> bool:
        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL, password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST, lang=QUOTEX_LANG,
                asset_default="EURUSD_otc", period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )
            self.client.set_account_mode(ACCOUNT_MODE)
            self.client.session_data = session_data
            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected via saved session: {reason}")
                return True
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
            return False
        except Exception as e:
            logger.warning(f"Session connection error: {e}")
            return False

    def _clean_stale_session(self):
        if not SESSION_FILE.exists():
            return
        try:
            with open(SESSION_FILE, "r") as f:
                session_data = json.load(f)
            if session_data.get("host") and session_data["host"] != QUOTEX_HOST:
                SESSION_FILE.unlink()
        except Exception:
            try:
                SESSION_FILE.unlink()
            except Exception:
                pass

    async def disconnect(self):
        if self.client and self._connected:
            try:
                await self.client.close()
            except Exception:
                pass
            finally:
                self._connected = False
                logger.info("Disconnected from Quotex")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_available_assets(self) -> list:
        """Get all available asset symbols from broker."""
        from bot.config import ALL_TARGET_ASSETS
        try:
            all_names = self.client.get_all_asset_name()
        except Exception:
            return ALL_TARGET_ASSETS
        if not all_names:
            return ALL_TARGET_ASSETS
        available = set()
        for item in all_names:
            if isinstance(item, (list, tuple)) and len(item) >= 1:
                available.add(item[0])
            elif isinstance(item, str):
                available.add(item)
        found = [a for a in ALL_TARGET_ASSETS if a in available]
        for sym in available:
            if sym not in found and (
                "_otc" in sym.lower()
                or any(fx in sym for fx in ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"])
                or sym.startswith("XAU") or sym.startswith("XAG")
                or sym in ["BTCUSD", "ETHUSD"]
            ):
                found.append(sym)
        logger.info(f"Found {len(found)} tradeable assets from {len(available)} total")
        return found

    async def fetch_historical_candles(
        self,
        asset: str,
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        progress_callback=None,
    ) -> list:
        """
        Fetch deep historical candle data using get_historical_candles().
        This is the correct method — get_candles_deep is deprecated.
        """
        if not self._connected:
            return []
        try:
            candles = await self.client.get_historical_candles(
                asset=asset,
                amount_of_seconds=amount_of_seconds,
                period=period,
                timeout=FETCH_BATCH_TIMEOUT,
                max_workers=FETCH_MAX_WORKERS,
                progress_callback=progress_callback,
            )
            if candles:
                logger.info(f"Fetched {len(candles)} candles for {asset}")
            return candles or []
        except Exception as e:
            logger.error(f"Error fetching candles for {asset}: {e}")
            return []

    async def fetch_recent_candles(
        self,
        asset: str,
        offset: int = 3600,
        period: int = CANDLE_PERIOD,
    ) -> list:
        """Fetch the most recent hour of candle data for cache gap-fill."""
        if not self._connected:
            return []
        try:
            candles = await self.client.get_candles(
                asset=asset,
                end_from_time=time.time(),
                offset=offset,
                period=period,
                timeout=15,
            )
            return candles or []
        except Exception as e:
            logger.error(f"Error fetching recent candles for {asset}: {e}")
            return []


# ─── Session file helpers ──────────────────────────────────────────────

def _load_session_file() -> dict:
    if not SESSION_FILE.exists():
        return {}
    try:
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_session_file(session_data: dict):
    try:
        session_data["host"] = QUOTEX_HOST
        with open(SESSION_FILE, "w") as f:
            json.dump(session_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save session: {e}")


# ─── Browser-based session extraction ─────────────────────────────────

async def _extract_session_via_browser(host, email, password, lang="en", timeout=120):
    """Open Playwright browser for manual login to bypass CloudFlare."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed for browser login.")
        return {}

    login_url = f"https://{host}/{lang}"
    logger.info(f"Opening browser for login at {login_url}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720}, locale=lang,
        )
        page = await context.new_page()
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(15):
                await asyncio.sleep(2)
                if "Just a moment" not in await page.title():
                    break
            await page.wait_for_selector('input[name="email"], input[type="email"]', timeout=15000)
            await page.locator('input[name="email"], input[type="email"]').fill(email)
            await page.locator('input[name="password"], input[type="password"]').fill(password)
            await page.locator('button[type="submit"], input[type="submit"]').click()
            await page.wait_for_url("**/trade**", timeout=timeout * 1000)
            session_data = await page.evaluate("""() => {
                const d = {token: null, cookies: document.cookie, user_agent: navigator.userAgent};
                if (window.settings && window.settings.token) d.token = window.settings.token;
                return d;
            }""")
            browser_cookies = await context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in browser_cookies)
            if cookie_str and not session_data.get("cookies"):
                session_data["cookies"] = cookie_str
            if not session_data.get("token"):
                import re
                content = await page.content()
                m = re.search(r'"token"\s*:\s*"([a-f0-9]{32,})"', content)
                if m:
                    session_data["token"] = m.group(1)
            await browser.close()
            return session_data
        except Exception as e:
            logger.error(f"Browser session extraction failed: {e}")
            await browser.close()
            return {}
