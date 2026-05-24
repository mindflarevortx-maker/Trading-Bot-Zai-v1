"""
Quotex API Client Wrapper for Trading Bot Zai v1.

Combines the best of both repos:
  - pyquotex (full API + indicators + streaming)
  - quotex-historical-data (get_candles_deep for unlimited history)

Provides a clean async interface for:
  - Authentication & connection
  - Fetching all available instruments
  - Getting deep historical candle data (30 days, 1-min)
  - Getting recent candle updates for cache merging

Connection Strategy (3-tier fallback):
  1. Try direct HTTP login via pyquotex (works if no CloudFlare)
  2. Try reusing saved session from session.json
  3. Try browser-based login via Playwright (solves CloudFlare)
  4. If all fail: guide user to manual session extraction
"""

import asyncio
import json
import logging
import time
import os
from typing import Optional

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, QUOTEX_LANG,
    ACCOUNT_MODE, CANDLE_PERIOD, HISTORY_SECONDS,
    PROXY_HTTP, PROXY_HTTPS, SESSION_FILE,
)

logger = logging.getLogger("quotex_client")


# ──────────────────────────────────────────────────────────────────────
# Login class patching — the core fix
# ──────────────────────────────────────────────────────────────────────

def _patch_login_host(host: str):
    """
    Patch the Login class's base_url class attributes so that the HTTP
    authentication flow targets the correct broker domain.

    The pyquotex Login class hardcodes:
        base_url = 'qxbroker.com'
        https_base_url = f'https://{base_url}'

    These are computed at class-definition time, so even if we pass
    host=market-qx.trade to the Quotex() constructor, the Login class
    still tries to connect to qxbroker.com for the sign-in page.

    The fix: override the CLASS ATTRIBUTES (not __init__) before any
    Login instance is created.  This works with both the old pyquotex
    (Navigator / _scraper) and the new pyquotex (Browser / _client)
    because we never touch __init__ or any instance methods.
    """
    patched = False

    for module_path in ("pyquotex.network.login", "quotex.network.login"):
        try:
            import importlib
            login_module = importlib.import_module(module_path)
            LoginClass = getattr(login_module, "Login", None)
            if LoginClass is not None:
                LoginClass.base_url = host
                LoginClass.https_base_url = f"https://{host}"
                logger.info(f"Patched Login.base_url → {host}")
                patched = True
                break
        except ImportError:
            continue

    if not patched:
        logger.warning(
            "Could not patch Login class base_url. "
            "Login may target the wrong host."
        )

    return patched


def _patch_ssl_verification():
    """
    Patch the Browser class to disable strict SSL verification.
    Custom broker mirrors often use SSL certs not in the default CA bundle.

    This replaces the Browser.__init__ to create an httpx.AsyncClient
    with verify=False instead of the custom SSL context.
    """
    for module_path in ("pyquotex.network.navigator", "quotex.network.navigator"):
        try:
            import importlib
            nav_module = importlib.import_module(module_path)

            BrowserClass = getattr(nav_module, "Browser", None)
            if BrowserClass is not None and hasattr(BrowserClass, "__init__"):
                if not getattr(BrowserClass, "_ssl_patched", False):
                    import httpx as _httpx
                    original_init = BrowserClass.__init__

                    def patched_init(self, *args, **kwargs):
                        # Call original init but we'll override the client after
                        try:
                            original_init(self, *args, **kwargs)
                        except Exception:
                            # If original init fails (e.g., SSL context error),
                            # set up minimal attributes
                            self.response = None
                            self.default_headers = None
                            self.headers = {}
                        
                        # Replace the httpx client with one that skips SSL verification
                        self._client = _httpx.AsyncClient(
                            verify=False,
                            timeout=30.0,
                            follow_redirects=True,
                            proxy=kwargs.get("proxy") if isinstance(kwargs.get("proxies"), str) else None,
                        )
                        # Also relax the SSL context for WebSocket connections
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

    logger.info("No SSL patching needed (or modules not found)")
    return False


# ──────────────────────────────────────────────────────────────────────
# Browser-based session extraction (solves CloudFlare challenges)
# ──────────────────────────────────────────────────────────────────────

async def _extract_session_via_browser(
    host: str,
    email: str,
    password: str,
    lang: str = "en",
    timeout: int = 120,
) -> dict:
    """
    Use Playwright to open a browser window, log in to Quotex,
    and extract the session data (SSID token + cookies).

    This bypasses CloudFlare because a real browser executes JavaScript
    and can solve the challenge.

    Returns dict with: {"token": ..., "cookies": ..., "user_agent": ...}
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "Playwright not installed. Install with: "
            "pip install playwright && playwright install chromium"
        )
        return {}

    base_url = f"https://{host}"
    login_url = f"{base_url}/{lang}"

    logger.info(f"Opening browser for login at {login_url}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Headful mode to avoid CloudFlare detection
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale=lang,
        )
        page = await context.new_page()

        try:
            # Navigate to login page
            await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for CloudFlare to resolve (up to 30 seconds)
            for i in range(15):
                title = await page.title()
                if "Just a moment" not in title:
                    break
                await asyncio.sleep(2)

            # Check if we're past CloudFlare
            title = await page.title()
            if "Just a moment" in title:
                logger.error("Could not bypass CloudFlare challenge")
                await browser.close()
                return {}

            # Wait for sign-in form
            await page.wait_for_selector(
                'input[name="email"], input[type="email"]',
                timeout=15000,
            )

            # Fill in credentials
            email_input = page.locator(
                'input[name="email"], input[type="email"]'
            )
            await email_input.fill(email)

            password_input = page.locator(
                'input[name="password"], input[type="password"]'
            )
            await password_input.fill(password)

            # Submit the form
            submit_btn = page.locator(
                'button[type="submit"], button.btn-login, '
                'input[type="submit"]'
            )
            await submit_btn.click()

            # Wait for navigation to trade page
            await page.wait_for_url(
                "**/trade**", timeout=timeout * 1000
            )

            # Extract session data from the page
            session_data = await page.evaluate("""
                () => {
                    const data = {
                        token: null,
                        cookies: document.cookie,
                        user_agent: navigator.userAgent,
                    };
                    // Try to extract from window.settings
                    if (window.settings && window.settings.token) {
                        data.token = window.settings.token;
                    }
                    return data;
                }
            """)

            # Also get cookies from browser context
            browser_cookies = await context.cookies()
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}" for c in browser_cookies
            )

            if cookie_str and not session_data.get("cookies"):
                session_data["cookies"] = cookie_str

            # If we didn't get the token from window.settings,
            # try to find it in the page source
            if not session_data.get("token"):
                content = await page.content()
                import re
                token_match = re.search(
                    r'window\.settings\s*=\s*\{[^}]*"token"\s*:\s*"([^"]+)"',
                    content,
                )
                if token_match:
                    session_data["token"] = token_match.group(1)

            logger.info(
                "Session extracted from browser: "
                f"token={'found' if session_data.get('token') else 'missing'}, "
                f"cookies={'found' if session_data.get('cookies') else 'missing'}"
            )

            await browser.close()
            return session_data

        except Exception as e:
            logger.error(f"Browser session extraction failed: {e}")
            await browser.close()
            return {}


# ──────────────────────────────────────────────────────────────────────
# Session file management
# ──────────────────────────────────────────────────────────────────────

def _load_session_file() -> dict:
    """Load session data from session.json."""
    if not SESSION_FILE.exists():
        return {}
    try:
        with open(SESSION_FILE, "r") as f:
            data = json.load(f)
        logger.info(f"Loaded session from {SESSION_FILE}")
        return data
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Could not load session file: {e}")
        return {}


def _save_session_file(session_data: dict):
    """Save session data to session.json."""
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump(session_data, f, indent=2)
        logger.info(f"Saved session to {SESSION_FILE}")
    except Exception as e:
        logger.warning(f"Could not save session file: {e}")


def _is_session_valid(session_data: dict) -> bool:
    """Check if session data has the minimum required fields."""
    return bool(session_data.get("token") and session_data.get("cookies"))


# ──────────────────────────────────────────────────────────────────────
# Main QuotexClient class
# ──────────────────────────────────────────────────────────────────────

class QuotexClient:
    """
    High-level async client for Quotex broker.
    Wraps the pyquotex library with deep-candle support.

    Connection strategy (3-tier fallback):
      1. Try direct HTTP login via pyquotex
      2. Try reusing saved session from session.json
      3. Try browser-based login via Playwright
    """

    def __init__(self):
        self.client = None
        self._connected = False
        self._proxies = None

        if PROXY_HTTPS:
            self._proxies = {"https": PROXY_HTTPS, "http": PROXY_HTTP or PROXY_HTTPS}

    async def connect(self) -> bool:
        """Connect to Quotex with full authentication flow (3-tier fallback)."""
        try:
            from quotex.stable_api import Quotex
            _module_prefix = "quotex"
        except ImportError:
            try:
                from pyquotex.stable_api import Quotex
                _module_prefix = "pyquotex"
            except ImportError:
                logger.error(
                    "Neither 'quotex' nor 'pyquotex' package found. "
                    "Install with: pip install pyquotex"
                )
                return False

        logger.info(f"Using {_module_prefix} library")

        # ─── Apply critical patches ────────────────────────────────
        _patch_login_host(QUOTEX_HOST)
        _patch_ssl_verification()

        # ─── Clean stale session ───────────────────────────────────
        self._clean_stale_session()

        # ─── Try Tier 1: Direct HTTP login ─────────────────────────
        logger.info(
            f"Connecting to {QUOTEX_HOST} as {QUOTEX_EMAIL}..."
        )

        connected = await self._try_direct_login(Quotex)
        if connected:
            return True

        # ─── Try Tier 2: Saved session ─────────────────────────────
        logger.info("Direct login failed. Trying saved session...")
        connected = await self._try_saved_session(Quotex)
        if connected:
            return True

        # ─── Try Tier 3: Browser-based login ──────────────────────
        logger.info(
            "Saved session failed. Trying browser-based login "
            "(this may open a browser window)..."
        )
        connected = await self._try_browser_login(Quotex)
        if connected:
            return True

        # ─── All methods failed ────────────────────────────────────
        logger.error(
            "All connection methods failed. Possible causes:\n"
            "  1. CloudFlare is blocking automated access\n"
            "  2. Invalid credentials\n"
            "  3. The broker domain is temporarily down\n\n"
            "Solutions:\n"
            "  • Run: python extract_session.py\n"
            "    (opens a browser for manual login)\n"
            "  • Or manually extract cookies from your browser\n"
            "    and save them to session.json"
        )
        return False

    async def _try_direct_login(self, Quotex) -> bool:
        """Tier 1: Try direct HTTP login via pyquotex."""
        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL,
                password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST,
                lang=QUOTEX_LANG,
                asset_default="EURUSD_otc",
                period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )

            if ACCOUNT_MODE == "PRACTICE":
                self.client.set_account_mode("PRACTICE")
            else:
                self.client.set_account_mode("REAL")

            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected via direct login: {reason}")
                return True
            else:
                logger.warning(f"Direct login failed: {reason}")
                return False

        except Exception as e:
            error_str = str(e)
            # Check if it's a CloudFlare/403 error
            if "403" in error_str or "Forbidden" in error_str:
                logger.info("CloudFlare challenge detected (HTTP 403)")
            else:
                logger.warning(f"Direct login error: {e}")
            return False

    async def _try_saved_session(self, Quotex) -> bool:
        """Tier 2: Try using a saved session from session.json."""
        session_data = _load_session_file()

        if not _is_session_valid(session_data):
            logger.info("No valid saved session found")
            return False

        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL,
                password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST,
                lang=QUOTEX_LANG,
                asset_default="EURUSD_otc",
                period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )

            if ACCOUNT_MODE == "PRACTICE":
                self.client.set_account_mode("PRACTICE")
            else:
                self.client.set_account_mode("REAL")

            # Inject saved session data
            self.client.session_data = session_data
            self.client.api = None  # Will be created in connect()

            # Force use of saved session by ensuring token exists
            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected via saved session: {reason}")
                return True
            else:
                logger.warning(f"Saved session failed: {reason}")
                # Session is stale — delete it
                if SESSION_FILE.exists():
                    SESSION_FILE.unlink()
                    logger.info("Deleted stale session file")
                return False

        except Exception as e:
            logger.warning(f"Saved session error: {e}")
            return False

    async def _try_browser_login(self, Quotex) -> bool:
        """Tier 3: Try browser-based login to extract session."""
        session_data = await _extract_session_via_browser(
            host=QUOTEX_HOST,
            email=QUOTEX_EMAIL,
            password=QUOTEX_PASSWORD,
            lang=QUOTEX_LANG,
        )

        if not _is_session_valid(session_data):
            logger.error("Browser login did not yield valid session data")
            return False

        # Save the session for future use
        _save_session_file(session_data)

        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL,
                password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST,
                lang=QUOTEX_LANG,
                asset_default="EURUSD_otc",
                period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )

            if ACCOUNT_MODE == "PRACTICE":
                self.client.set_account_mode("PRACTICE")
            else:
                self.client.set_account_mode("REAL")

            # Inject browser-extracted session
            self.client.session_data = session_data

            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected via browser-extracted session: {reason}")
                return True
            else:
                logger.warning(f"Browser session failed: {reason}")
                return False

        except Exception as e:
            logger.warning(f"Browser session connection error: {e}")
            return False

    def _clean_stale_session(self):
        """Remove session file if it was created for a different host."""
        if not SESSION_FILE.exists():
            return

        try:
            with open(SESSION_FILE, "r") as f:
                session_data = json.load(f)

            session_host = session_data.get("host", "")
            if session_host and session_host != QUOTEX_HOST:
                SESSION_FILE.unlink()
                logger.info(
                    f"Removed stale session for {session_host} "
                    f"(current host: {QUOTEX_HOST})"
                )
            elif not _is_session_valid(session_data):
                # Token or cookies missing — stale
                SESSION_FILE.unlink()
                logger.info("Removed invalid session file")
        except (json.JSONDecodeError, Exception):
            try:
                SESSION_FILE.unlink()
                logger.info("Removed corrupted session file")
            except Exception:
                pass

    async def disconnect(self):
        """Gracefully disconnect from Quotex."""
        if self.client and self._connected:
            try:
                await self.client.close()
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
            finally:
                self._connected = False
                logger.info("Disconnected from Quotex")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_all_instruments(self) -> list:
        """Fetch all available instruments from the broker."""
        if not self._connected:
            logger.error("Not connected. Call connect() first.")
            return []

        try:
            instruments = await self.client.get_instruments(timeout=30)
            logger.info(f"Received {len(instruments) if instruments else 0} instruments")
            return instruments or []
        except Exception as e:
            logger.error(f"Failed to get instruments: {e}")
            return []

    async def get_asset_names(self) -> list:
        """Get list of [symbol, display_name] for all assets."""
        if not self._connected:
            return []
        try:
            return self.client.get_all_asset_name()
        except Exception as e:
            logger.error(f"Failed to get asset names: {e}")
            return []

    async def get_asset_codes(self) -> dict:
        """Get {symbol: code} mapping for all assets."""
        if not self._connected:
            return {}
        try:
            return await self.client.get_all_assets()
        except Exception as e:
            logger.error(f"Failed to get asset codes: {e}")
            return {}

    async def get_available_assets(self) -> list:
        """
        Get all available and currently open asset symbols.
        Filters to include forex, OTC, commodities, crypto, and indices.
        """
        from bot.config import ALL_TARGET_ASSETS

        all_names = await self.get_asset_names()
        if not all_names:
            logger.warning("Could not fetch asset names, using default list")
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

    async def fetch_deep_candles(
        self,
        asset: str,
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        progress_callback=None,
    ) -> list:
        """Fetch deep historical candle data (30+ days of 1-min candles)."""
        if not self._connected:
            logger.error(f"Cannot fetch candles for {asset}: not connected")
            return []

        try:
            if hasattr(self.client, 'get_candles_deep'):
                candles = await self.client.get_candles_deep(
                    asset=asset,
                    amount_of_seconds=amount_of_seconds,
                    period=period,
                    timeout=30,
                    progress_callback=progress_callback,
                )
            else:
                candles = await self.client.get_historical_candles(
                    asset=asset,
                    amount_of_seconds=amount_of_seconds,
                    period=period,
                    timeout=30,
                )

            if candles:
                logger.info(f"Fetched {len(candles)} candles for {asset}")
            else:
                logger.warning(f"No candles returned for {asset}")

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
        """Fetch the most recent hour of candle data for cache merging."""
        if not self._connected:
            return []

        try:
            end_time = time.time()
            candles = await self.client.get_candles(
                asset=asset,
                end_from_time=end_time,
                offset=offset,
                period=period,
                timeout=15,
            )
            return candles or []

        except Exception as e:
            logger.error(f"Error fetching recent candles for {asset}: {e}")
            return []

    async def get_payout(self, asset: str, timeframe: int = 60) -> float:
        """Get payout percentage for an asset."""
        if not self._connected:
            return 0.0
        try:
            result = self.client.get_payout_by_asset(asset, timeframe)
            if isinstance(result, dict):
                return float(result.get("turbo", 0))
            return float(result) if result else 0.0
        except Exception:
            return 0.0
