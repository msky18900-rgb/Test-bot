import os
import logging
import tempfile
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from youtube_uploader import upload_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["8646298365:AAH95QvkjsTBW-IT78vvTxrSYqLpFQjWvTs"]
ALLOWED_USER_ID = int(os.environ["8001413907"])


async def post_init(application):
    """Auto-register webhook on startup if WEBHOOK_URL is set."""
    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook registered: {webhook_url}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Send or forward me a video and I'll upload it to your YouTube channel.\n\n"
        "The caption you add will become the video title."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    message = update.message
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

        video_id = await asyncio.to_thread(upload_video, tmp_path, title)

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
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        port = int(os.environ.get("PORT", 10000))
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
        )
    else:
        logger.info("No WEBHOOK_URL set — running in polling mode")
        app.run_polling()


if __name__ == "__main__":
    main()
