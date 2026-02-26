"""Telegram frontend provider."""
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config.settings import get_settings
from core.db import enqueue_task

logger = logging.getLogger(__name__)


class TelegramProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.app = (
            Application.builder()
            .token(self.settings.telegram_bot_token)
            .build()
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Pie-Brain online. Send me a task and I'll route it."
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text or ""
        logger.info("Telegram message from %s: %r", update.effective_user.id, text)
        task_id = await enqueue_task(self.settings.db_path, text)
        await update.message.reply_text(f"Task #{task_id} queued.")

    def run(self) -> None:
        """Start polling (blocking)."""
        logger.info("Telegram bot polling…")
        self.app.run_polling()
