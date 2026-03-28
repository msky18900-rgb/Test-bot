import os
import logging
import tempfile
import asyncio
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, filters, ConversationHandler
)
from youtube_uploader import upload_video_with_creds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = "8646298365:AAH95QvkjsTBW-IT78vvTxrSYqLpFQjWvTs"
ALLOWED_USER_ID = 8001413907

SCOPES     = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "/tmp/yt_token.json"

ASK_CLIENT_ID, ASK_CLIENT_SECRET, ASK_CALLBACK_URL = range(3)

pending = {}


def get_render_url():
    return os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")


def make_flow(client_id, client_secret):
    redirect_uri = f"{get_render_url()}/oauth2callback"
    client_config = {
        "web": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = redirect_uri
    return flow


def load_credentials():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I upload videos to your YouTube channel.\n\n"
        "First authorize YouTube by sending /auth\n"
        "Then just forward me any video!"
    )


async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Let's connect your YouTube account.\n\n"
        "Go to https://console.cloud.google.com/apis/credentials\n\n"
        "Find your OAuth 2.0 Client ID and paste it below 👇"
    )
    return ASK_CLIENT_ID


async def got_client_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending["client_id"] = update.message.text.strip()
    await update.message.reply_text("Got it! Now paste your Client Secret 👇")
    return ASK_CLIENT_SECRET


async def got_client_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending["client_secret"] = update.message.text.strip()

    try:
        flow = make_flow(pending["client_id"], pending["client_secret"])
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        await update.message.reply_text(
            f"✅ Click this link to authorize YouTube:\n\n{auth_url}\n\n"
            f"After approving, your browser will show an error page — that's normal!\n"
            f"Copy the full URL from your browser's address bar and paste it here 👇"
        )
        return ASK_CALLBACK_URL

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END


async def got_callback_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    callback_url = update.message.text.strip()

    try:
        flow = make_flow(pending["client_id"], pending["client_secret"])
        flow.fetch_token(authorization_response=callback_url)
        creds = flow.credentials

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

        await update.message.reply_text(
            "🎉 YouTube authorized successfully!\n\n"
            "Now forward me any video and I'll upload it to your channel."
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed: {e}\n\n"
            "Make sure you copied the full URL from your browser."
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    creds = load_credentials()
    if not creds:
        await update.message.reply_text(
            "⚠️ YouTube not authorized yet. Send /auth to connect."
        )
        return

    message  = update.message
    file_obj = message.video or message.document
    if not file_obj:
        await update.message.reply_text("Please send a video file.")
        return

    title = (
        message.caption
        or getattr(file_obj, "file_name", None)
        or "Uploaded via Telegram Bot"
    )

    status_msg = await message.reply_text("⬇️ Downloading video...")
    tmp_path = None

    try:
        tg_file = await context.bot.get_file(file_obj.file_id)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)
        await status_msg.edit_text("⬆️ Uploading to YouTube...")

        video_id = await asyncio.to_thread(upload_video_with_creds, tmp_path, title, creds)

        await status_msg.edit_text(
            f"✅ Done!\nhttps://www.youtube.com/watch?v={video_id}"
        )
    except Exception as e:
        logger.exception("Upload failed")
        await status_msg.edit_text(f"❌ Failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", auth_start)],
        states={
            ASK_CLIENT_ID:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_client_id)],
            ASK_CLIENT_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_client_secret)],
            ASK_CALLBACK_URL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_callback_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(auth_conv)
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
