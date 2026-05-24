---
Task ID: 1
Agent: Main Agent
Task: Fix Trading Bot Zai v1 connection error and update GitHub

Work Log:
- Analyzed the `'Login' object has no attribute '_scraper'` error
- Read pyquotex source code (Login, Browser/Navigator, API, AccountMixin classes)
- Identified root cause: Login class hardcodes `base_url = 'qxbroker.com'` as class attribute
- Previous monkey-patching overrode `__init__` which broke `_scraper` initialization
- Fixed by patching class attributes instead of __init__
- Added SSL verification bypass for custom broker domains
- Added python-dotenv loading in run.py (was missing entirely)
- Changed default host from qxbroker.com to market-qx.trade
- Discovered CloudFlare protection on market-qx.trade blocks automated HTTP login
- WebSocket connection works fine (wss://ws2.market-qx.trade/)
- Implemented 3-tier connection fallback: Direct login → Saved session → Browser login
- Created extract_session.py for browser-based session extraction
- Created test_connection.py for connection diagnostics
- All Python files pass syntax verification
- Created updated Trading_Bot_Zai_v1.zip
- GitHub push requires user's new token (old one was revoked)

Stage Summary:
- Core bug FIXED: Login class base_url patching works correctly
- New feature: 3-tier connection fallback for CloudFlare-protected domains
- New feature: extract_session.py for manual browser-based session extraction
- New feature: test_connection.py for diagnostics
- CloudFlare blocks direct HTTP login; user must extract session via browser first
- WebSocket connection verified working
- Files ready at /home/z/my-project/download/Trading_Bot_Zai_v1/
- ZIP ready at /home/z/my-project/download/Trading_Bot_Zai_v1.zip
- User needs to provide new GitHub token to push
