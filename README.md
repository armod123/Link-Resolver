# ⚡ Link Resolver

A Playwright-based tool that automatically navigates through ad-heavy redirect chains (rinku.pro, 7mb.io, Fly Inc shorteners) and extracts the final destination URL.

## How It Works

These link shorteners (rinku.pro, 7mb.io) force you through multiple pages with:
- Countdown timers
- "Click to continue" buttons
- Tab-focus detection (pauses timer when you switch tabs)
- Rotating intermediate ad domains

This tool uses a **headless browser** (Playwright + Chromium) to:
1. Navigate to the shortener URL
2. Inject JavaScript to bypass timer slowdowns and focus-detection
3. Automatically click through "Continue" / "Get Link" buttons
4. Block ad images & tracking scripts for speed
5. Close popup windows opened by ad scripts
6. Return the final destination URL

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install Playwright's Chromium browser
playwright install chromium

# 3. Run the web app
python app.py
```

Then open **http://localhost:5000** in your browser.

## Usage

### Web Interface
1. Paste a rinku.pro / 7mb.io link into the input field
2. Click "Resolve"
3. Watch the real-time log as the bot navigates through the redirect chain
4. Click the final URL or copy it

### Command Line
```bash
python resolver.py "https://rinku.pro/hSzkppLs"
```

### As a Python Module
```python
import asyncio
from resolver import resolve_link

async def main():
    result = await resolve_link("https://rinku.pro/hSzkppLs")
    if result.success:
        print(f"Final URL: {result.final_url}")
    else:
        print(f"Failed: {result.error}")

asyncio.run(main())
```

## Telegram Bot Integration

To integrate with a Telegram bot, you can use `python-telegram-bot`:

```bash
pip install python-telegram-bot
```

```python
# telegram_bot.py (example)
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from resolver import resolve_link

BOT_TOKEN = "YOUR_BOT_TOKEN"

async def handle_link(update: Update, context):
    url = update.message.text.strip()
    if "rinku.pro" in url or "7mb.io" in url:
        msg = await update.message.reply_text("🔄 Resolving link...")
        result = await resolve_link(url)
        if result.success:
            await msg.edit_text(f"✅ Final URL:\n{result.final_url}")
        else:
            await msg.edit_text(f"❌ Failed: {result.error}")

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
```

## Limitations

- **CAPTCHAs**: If the shortener serves a CAPTCHA, the bot cannot solve it automatically. It will retry by reloading the page.
- **Domain rotation**: Fly Inc changes its intermediate domains frequently. The known domains list in `resolver.py` may need updating.
- **Anti-bot detection**: Some shorteners detect headless browsers. The tool uses stealth techniques but may not always succeed.
- **Rate limiting**: Don't hammer the shortener with too many requests — you may get temporarily blocked.

## Project Structure

```
link-resolver/
├── app.py              # Flask web server with SSE streaming
├── resolver.py         # Core Playwright-based link resolver
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI with live progress log
└── README.md
```
