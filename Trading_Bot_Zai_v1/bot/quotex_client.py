"""
Quotex API Client Wrapper for Trading Bot Zai v1.

Wraps the pyquotex library, fixing the hardcoded Login URL issue
and providing a clean async interface for:
  - Authentication & connection (with correct host)
  - Fetching all available instruments
  - Getting deep historical candle data (30 days, 1-min)
  - Getting recent candle updates for cache merging
"""

import asyncio
import logging
import time
from typing import Optional

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, QUOTEX_LANG,
    ACCOUNT_MODE, CANDLE_PERIOD, HISTORY_SECONDS,
    PROXY_HTTP, PROXY_HTTPS,
)

logger = logging.getLogger("quotex_client")


def _patch_login_host(host: str):
    """
    Monkey-patch the pyquotex Login class to use the correct host.

    The pyquotex Login class has a HARDCODED base_url = 'qxbroker.com'.
    This means even if we pass host='market-qx.trade' to Quotex(),
    the login HTTP requests still go to qxbroker.com — causing
    'Connection reset by peer' errors.

    This patch fixes the Login class to use the correct host.
    Must be called BEFORE creating the Quotex instance.
    """
    try:
        from pyquotex.network.login import Login
        Login.base_url = host
        Login.https_base_url = f"https://{host}"
        logger.info(f"Patched Login class to use host: {host}")
    except ImportError:
        # Try the quotex-historical-data package
        try:
            from quotex.http.login import Login
            Login.base_url = host
            Login.https_base_url = f"https://{host}"
            logger.info(f"Patched Login class (quotex-hd) to use host: {host}")
        except ImportError:
            logger.warning("Could not patch Login class — login may fail")


def _patch_ssl_verify():
    """
    Monkey-patch the pyquotex Browser class to disable strict SSL verification.

    Some Quotex broker mirrors (like market-qx.trade) use SSL certificates
    that are not in certifi's CA bundle. This causes CERTIFICATE_VERIFY_FAILED
    errors during the HTTP login flow.

    This patch replaces the Browser.__init__ to create an httpx client with
    verify=False, bypassing the strict SSL context entirely.
    """
    try:
        import httpx
        from pyquotex.network.navigator import Browser, USER_AGENT_DEFAULT

        def _patched_init(self, *args, **kwargs):
            import ssl
            self.response = None
            self.default_headers = None
            self.source_address = kwargs.pop('source_address', None)
            self.server_hostname = kwargs.pop('server_hostname', None)
            self.proxies = kwargs.pop('proxies', None)
            self.debug = kwargs.pop('debug', False)

            self.headers = {
                "User-Agent": USER_AGENT_DEFAULT,
            }

            # Create permissive SSL context (for WebSocket compatibility)
            self._ssl_context = ssl.create_default_context()
            self._ssl_context.check_hostname = False
            self._ssl_context.verify_mode = ssl.CERT_NONE

            # Create httpx client with verify=False to bypass SSL
            self._client = httpx.AsyncClient(
                verify=False,
                timeout=30.0,
                follow_redirects=True,
                proxy=self.proxies if isinstance(self.proxies, str) else None,
            )

            if self.debug:
                import logging
                logging.getLogger("Browser").setLevel(logging.DEBUG)

        Browser.__init__ = _patched_init
        logger.info("Patched Browser to disable SSL verification (verify=False)")

    except ImportError:
        logger.warning("Could not patch Browser SSL — SSL errors may occur")


class QuotexClient:
    """
    High-level async client for Quotex broker.
    Wraps the pyquotex library with proper host configuration.
    """

    def __init__(self):
        self.client = None
        self._connected = False
        self._proxies = None

        if PROXY_HTTPS:
            self._proxies = {"https": PROXY_HTTPS, "http": PROXY_HTTP or PROXY_HTTPS}

    async def connect(self) -> bool:
        """Connect to Quotex with full authentication flow."""
        # ─── Step 1: Import pyquotex ───────────────────────────────
        try:
            from pyquotex.stable_api import Quotex
            logger.info("Using pyquotex library")
        except ImportError:
            try:
                from quotex.stable_api import Quotex
                logger.info("Using quotex (historical-data) library")
            except ImportError:
                logger.error(
                    "Neither 'quotex' nor 'pyquotex' package found. "
                    "Install with: pip install pyquotex"
                )
                return False

        # ─── Step 2: Patch Login class with correct host ───────────
        _patch_login_host(QUOTEX_HOST)

        # ─── Step 2b: Patch SSL verification for non-standard hosts ─
        _patch_ssl_verify()

        try:
            # ─── Step 3: Create Quotex instance ────────────────────
            self.client = Quotex(
                email=QUOTEX_EMAIL,
                password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST,
                lang=QUOTEX_LANG,
                asset_default="EURUSD_otc",
                period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )

            # ─── Step 4: Also patch the API's Login after creation ─
            # The Quotex.connect() creates QuotexAPI which creates Login()
            # We need to ensure Login.base_url is patched before connect
            _patch_login_host(QUOTEX_HOST)

            # ─── Step 5: Set account mode ──────────────────────────
            if ACCOUNT_MODE == "PRACTICE":
                self.client.set_account_mode("PRACTICE")
            else:
                self.client.set_account_mode("REAL")

            # ─── Step 6: Attempt connection ────────────────────────
            logger.info(f"Connecting to {QUOTEX_HOST} as {QUOTEX_EMAIL}...")
            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected to Quotex successfully: {reason}")
                return True
            else:
                logger.error(f"Connection failed: {reason}")
                # Try once more with fresh session
                logger.info("Retrying with fresh session...")
                self._clean_stale_session()
                # Re-create the client
                self.client = Quotex(
                    email=QUOTEX_EMAIL,
                    password=QUOTEX_PASSWORD,
                    host=QUOTEX_HOST,
                    lang=QUOTEX_LANG,
                    asset_default="EURUSD_otc",
                    period_default=CANDLE_PERIOD,
                    proxies=self._proxies,
                )
                self.client.set_account_mode("PRACTICE" if ACCOUNT_MODE == "PRACTICE" else "REAL")
                _patch_login_host(QUOTEX_HOST)

                check2, reason2 = await self.client.connect()
                if check2:
                    self._connected = True
                    logger.info(f"Connected on retry: {reason2}")
                    return True
                else:
                    logger.error(f"Retry also failed: {reason2}")
                    return False

        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            return False

    def _clean_stale_session(self):
        """Remove stale session.json that may have wrong cookies/token."""
        try:
            from pathlib import Path
            session_file = Path("session.json")
            if session_file.exists():
                # Read and check if it's for the correct host
                import json
                with open(session_file, "r") as f:
                    sessions = json.load(f)

                # Remove the session for our email (force fresh login)
                if QUOTEX_EMAIL in sessions:
                    sessions[QUOTEX_EMAIL] = {
                        "cookies": None,
                        "token": None,
                        "user_agent": sessions[QUOTEX_EMAIL].get("user_agent")
                    }
                    with open(session_file, "w") as f:
                        json.dump(sessions, f, indent=4)
                    logger.info(f"Cleaned stale session for {QUOTEX_EMAIL}")
        except Exception as e:
            logger.debug(f"Session cleanup note: {e}")

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
        """
        Fetch all available instruments from the broker.
        Returns the raw instrument list from WebSocket.
        """
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
            # get_all_asset_name() is SYNC (not async)
            return self.client.get_all_asset_name() or []
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
        Returns list of asset symbol strings.
        """
        from bot.config import ALL_TARGET_ASSETS

        all_names = await self.get_asset_names()
        if not all_names:
            logger.warning("Could not fetch asset names, using default list")
            return ALL_TARGET_ASSETS

        # all_names is [[symbol, display_name], ...]
        available = set()
        for item in all_names:
            if isinstance(item, (list, tuple)) and len(item) >= 1:
                available.add(item[0])
            elif isinstance(item, str):
                available.add(item)

        # Filter to our target assets that are available
        found = [a for a in ALL_TARGET_ASSETS if a in available]

        # Also add any OTC or forex-like assets we might have missed
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
        """
        Fetch deep historical candle data.
        Uses get_historical_candles() from pyquotex (parallel workers).

        Returns list of candle dicts: [{time, open, close, high, low}, ...]
        """
        if not self._connected:
            logger.error(f"Cannot fetch candles for {asset}: not connected")
            return []

        try:
            # get_historical_candles is the modern method (was get_candles_deep)
            candles = await self.client.get_historical_candles(
                asset=asset,
                amount_of_seconds=amount_of_seconds,
                period=period,
                timeout=30,
                max_workers=3,  # Conservative to avoid rate limiting
                progress_callback=progress_callback,
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
        """
        Fetch the most recent hour of candle data for cache merging.
        Uses the standard get_candles() with a 1-hour offset.

        Returns list of candle dicts.
        """
        if not self._connected:
            return []

        try:
            end_time = time.time()
            candles = await self.client.get_candles(
                asset,
                end_from_time=end_time,
                offset=offset,
                period=period,
                timeout=15,
            )
            return candles or []

        except Exception as e:
            logger.error(f"Error fetching recent candles for {asset}: {e}")
            return []

    async def get_payout(self, asset: str, timeframe: str = "1") -> float:
        """Get payout percentage for an asset."""
        if not self._connected:
            return 0.0
        try:
            result = self.client.get_payout_by_asset(asset, timeframe)
            if isinstance(result, dict):
                return float(result.get("turbo_payment", 0))
            return float(result) if result else 0.0
        except Exception:
            return 0.0
