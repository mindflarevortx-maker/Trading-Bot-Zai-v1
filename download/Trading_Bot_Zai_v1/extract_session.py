#!/usr/bin/env python3
"""
Quotex Session Extractor for Trading Bot Zai v1.

Opens a real browser window for you to log in to Quotex.
After successful login, it extracts the session token and cookies
and saves them to session.json for the trading bot to use.

This is needed when CloudFlare blocks automated login attempts.

Usage:
    python extract_session.py

Requirements:
    pip install playwright
    playwright install chromium
"""

import asyncio
import json
import re
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from bot.config import QUOTEX_HOST, QUOTEX_LANG, SESSION_FILE


async def extract_session():
    """Open a browser, let the user log in, and extract session data."""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright not installed!")
        print("   Install with: pip install playwright")
        print("   Then run:     playwright install chromium")
        return False

    base_url = f"https://{QUOTEX_HOST}"
    login_url = f"{base_url}/{QUOTEX_LANG}"

    print(f"\n{'='*60}")
    print(f"  Quotex Session Extractor")
    print(f"{'='*60}")
    print(f"  Domain: {QUOTEX_HOST}")
    print(f"  Login URL: {login_url}")
    print(f"  Session file: {SESSION_FILE}")
    print(f"{'='*60}")
    print()
    print("A browser window will open. Please:")
    print("  1. Solve the CloudFlare challenge if prompted")
    print("  2. Log in with your Quotex credentials")
    print("  3. Wait until you see the trading dashboard")
    print()
    print("The script will automatically detect when you're logged in")
    print("and extract the session data.")
    print()

    input("Press Enter to open the browser...")

    async with async_playwright() as p:
        # Launch browser in headful mode (visible window)
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--start-maximized',
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale=QUOTEX_LANG,
        )

        page = await context.new_page()

        print(f"\n🌐 Navigating to {login_url}...")

        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️  Navigation warning: {e}")
            print("   The page may still be loading. Continuing...")

        # Wait for the user to log in (up to 5 minutes)
        print("\n⏳ Waiting for you to log in...")
        print("   (The script will auto-detect when you reach the trading page)")
        print()

        max_wait = 300  # 5 minutes
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            try:
                url = page.url
                title = await page.title()

                # Check if user has reached the trading dashboard
                if "trade" in url.lower() or "trade" in title.lower():
                    print(f"\n✅ Detected trading dashboard!")
                    print(f"   URL: {url}")
                    print(f"   Title: {title}")
                    break

                # Show progress
                if elapsed % 10 == 0:
                    print(f"   [{elapsed}s] Still waiting... (URL: {url[:60]}...)")

            except Exception:
                pass
        else:
            print("\n⏰ Timeout: 5 minutes passed without detecting the trading page.")
            print("   Trying to extract session data anyway...")

        # ─── Extract session data ──────────────────────────────────
        print("\n📋 Extracting session data...")

        session_data = {"host": QUOTEX_HOST}

        # Method 1: Extract from window.settings
        try:
            settings_data = await page.evaluate("""
                () => {
                    try {
                        if (window.settings) {
                            return {
                                token: window.settings.token || null,
                            };
                        }
                    } catch (e) {}
                    return null;
                }
            """)

            if settings_data and settings_data.get("token"):
                session_data["token"] = settings_data["token"]
                print(f"   ✅ Token extracted from window.settings")
        except Exception as e:
            print(f"   ⚠️  window.settings extraction failed: {e}")

        # Method 2: Extract token from page source
        if not session_data.get("token"):
            try:
                content = await page.content()
                token_match = re.search(
                    r'"token"\s*:\s*"([a-f0-9]{32,})"',
                    content,
                )
                if token_match:
                    session_data["token"] = token_match.group(1)
                    print(f"   ✅ Token extracted from page source")
            except Exception as e:
                print(f"   ⚠️  Page source extraction failed: {e}")

        # Method 3: Extract cookies
        try:
            browser_cookies = await context.cookies()
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}" for c in browser_cookies
            )
            session_data["cookies"] = cookie_str
            print(f"   ✅ Cookies extracted ({len(browser_cookies)} cookies)")
        except Exception as e:
            print(f"   ⚠️  Cookie extraction failed: {e}")

        # Method 4: Extract user agent
        try:
            user_agent = await page.evaluate("navigator.userAgent")
            session_data["user_agent"] = user_agent
            print(f"   ✅ User-Agent extracted")
        except Exception:
            session_data["user_agent"] = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )

        # Save session
        if session_data.get("token") and session_data.get("cookies"):
            with open(SESSION_FILE, "w") as f:
                json.dump(session_data, f, indent=2)

            print(f"\n✅ Session saved to {SESSION_FILE}")
            print(f"   Token: {session_data['token'][:20]}...")
            print(f"   Cookies length: {len(session_data['cookies'])} chars")
            print()
            print("🚀 You can now run the trading bot:")
            print("   python run.py")
            success = True
        else:
            print(f"\n❌ Could not extract complete session data:")
            print(f"   Token: {'found' if session_data.get('token') else 'MISSING'}")
            print(f"   Cookies: {'found' if session_data.get('cookies') else 'MISSING'}")
            print()
            print("💡 Tips:")
            print("   1. Make sure you're on the trading dashboard (not login page)")
            print("   2. Try refreshing the page and running this script again")
            print("   3. Check that the domain in .env is correct")
            success = False

        # Close browser
        await browser.close()
        print("\nBrowser closed.")
        return success


def main():
    try:
        success = asyncio.run(extract_session())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Cancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
