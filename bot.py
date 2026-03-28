import os
import logging
import tempfile
import asyncio
import threading
import json
from flask import Flask, request, redirect, session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from youtube_uploader import upload_video_with_creds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = "8646298365:AAH95QvkjsTBW-IT78vvTxrSYqLpFQjWvTs"
ALLOWED_USER_ID = 8001413907

SCOPES     = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "/tmp/yt_token.json"
flask_app  = Flask(__name__)
flask_app.secret_key = os.urandom(24)

oauth_config = {}


@flask_app.route("/")
def index():
    return "<h2>Bot is running ✅</h2><p><a href='/setup'>Set up YouTube OAuth</a></p>"


@flask_app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        oauth_config["client_id"]     = request.form["client_id"].strip()
        oauth_config["client_secret"] = request.form["client_secret"].strip()
        flow = _make_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["state"] = state
        return redirect(auth_url)

    return """
    <html><body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px">
    <h2>YouTube OAuth Setup</h2>
    <p>Enter your Google OAuth credentials from
    <a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console</a>.</p>
    <form method="POST">
      <label>Client ID</label><br>
      <input name="client_id" style="width:100%;padding:8px;margin:6px 0 16px;box-sizing:border-box" required><br>
      <label>Client Secret</label><br>
      <input name="client_secret" style="width:100%;padding:8px;margin:6px 0 16px;box-sizing:border-box" required><br>
      <button type="submit" style="padding:10px 24px;background:#4285F4;color:white;border:none;border-radius:4px;cursor:pointer">
        Authorize with Google
      </button>
    </form>
    </body></html>
    """


@flask_app.route("/oauth2callback")
def oauth2callback():
    if not oauth_config.get("client_id"):
        return "Session expired. Please go back to /setup and try again.", 400

    flow = _make_flow()
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    token_data = json.loads(creds.to_json())
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

    return """
    <html><body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px">
    <h2>✅ Authorization successful!</h2>
    <p>Your YouTube token has been saved. The bot is ready to upload videos.</p>
    <p>Just forward any video to your Telegram bot.</p>
    </body></html>
    """


def _make_flow() -> Flow:
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
    redirect_uri = f"{render_url}/oauth2callback"
    client_config = {
        "web": {
            "client_id":     oauth_config["client_id"],
            "client_secret": oauth_config["client_secret"],
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
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
    await update.message.reply_text(
        f"👋 Hi! Before using me, make sure YouTube is authorized.\n\n"
        f"Set up here: {render_url}/setup\n\n"
        f"Then forward me any video — the caption becomes the YouTube title."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    creds = load_credentials()
    if not creds:
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
        await update.message.reply_text(
            f"⚠️ YouTube not authorized yet.\nPlease visit: {render_url}/setup"
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


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


def main():
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    logger.info("Flask server started")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    logger.info("Telegram bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
