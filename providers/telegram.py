"""Telegram frontend provider."""
import asyncio
import logging
from pathlib import Path

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import guardian
from config.settings import get_settings
from core.db import (
    enqueue_task,
    get_completed_unnotified,
    get_recent_tasks,
    get_task_by_id,
    mark_notified,
)

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "*Pie-Brain* — task routing engine\n\n"
    "Just send me a message and I'll route it to the right tool.\n\n"
    "Commands:\n"
    "/start — welcome message\n"
    "/help — show this message\n"
    "/status \\[task\\_id\\] — check task status (omit id for last 5 tasks)\n"
)


class TelegramProvider:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.app = (
            Application.builder()
            .token(self.settings.telegram_bot_token)
            .post_init(self._on_startup)
            .build()
        )
        self._register_handlers()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _on_startup(self, application: Application) -> None:
        """Registered as post_init hook — runs inside run_polling()'s event loop."""
        asyncio.create_task(self._deliver_results())
        logger.info("Result-delivery background task started.")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

    def _is_authorized(self, update: Update) -> bool:
        if not self.settings.telegram_allowed_user_ids:
            return True  # open mode — no allowlist configured
        user = update.effective_user
        return user is not None and user.id in self.settings.telegram_allowed_user_ids

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update) or update.message is None:
            return
        await update.message.reply_text("Pie-Brain online. Send me a task and I'll route it.")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update) or update.message is None:
            return
        await update.message.reply_markdown_v2(HELP_TEXT)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update) or update.message is None:
            return

        args = context.args or []
        if args:
            try:
                task_id = int(args[0])
            except ValueError:
                await update.message.reply_text("Usage: /status [task_id]")
                return
            task = await get_task_by_id(self.settings.db_path, task_id)
            if task is None:
                await update.message.reply_text(f"Task #{task_id} not found.")
            else:
                tool = task.tool_name or "unrouted"
                await update.message.reply_text(
                    f"Task #{task.id}\n"
                    f"Status:  {task.status.value}\n"
                    f"Tool:    {tool}\n"
                    f"Request: {task.request_text[:120]}"
                )
        else:
            tasks = await get_recent_tasks(self.settings.db_path, limit=5)
            if not tasks:
                await update.message.reply_text("No tasks yet.")
                return
            lines = ["Recent tasks (newest first):"]
            for t in tasks:
                snippet = t.request_text[:60]
                if len(t.request_text) > 60:
                    snippet += "…"
                lines.append(f"#{t.id} [{t.status.value}] {snippet}")
            await update.message.reply_text("\n".join(lines))

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.effective_user is None:
            return
        if not self._is_authorized(update):
            await update.message.reply_text("Unauthorized.")
            return

        text = update.message.text or ""
        chat_id = update.effective_chat.id if update.effective_chat else None
        logger.info("Telegram message from user_id=%d: %r", update.effective_user.id, text)

        ok, reason = guardian.validate_message(text)
        if not ok:
            logger.warning("Guardian: rejected message from user_id=%d: %s", update.effective_user.id, reason)
            await update.message.reply_text(f"Message rejected: {reason}")
            return

        task_id = await enqueue_task(self.settings.db_path, text, chat_id=chat_id)
        await update.message.reply_text(f"Task #{task_id} queued.")

    # ------------------------------------------------------------------
    # Result delivery
    # ------------------------------------------------------------------

    async def _deliver_results(self) -> None:
        """Background loop: poll for done tasks and send results back to the user."""
        bot = Bot(token=self.settings.telegram_bot_token)
        interval = self.settings.telegram_result_poll_interval
        while True:
            try:
                tasks = await get_completed_unnotified(self.settings.db_path)
                for task in tasks:
                    await self._send_result(bot, task)
            except Exception:
                logger.exception("Error in result-delivery loop")
            await asyncio.sleep(interval)

    async def _send_result(self, bot: Bot, task) -> None:
        """Send the completed task result to the originating chat."""
        inbox = Path(self.settings.brain_inbox)
        result_text = f"Task #{task.id} complete (tool: {task.tool_name or 'unknown'})."

        # Look for output files written by this specific task (prefixed with task id)
        if inbox.exists():
            candidates = sorted(
                inbox.glob(f"{task.id}_*.md"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                content = candidates[0].read_text(encoding="utf-8")
                if len(content) > 4000:
                    content = content[:4000] + "\n\n…(truncated)"
                result_text = content

        try:
            await bot.send_message(chat_id=task.chat_id, text=result_text)
            await mark_notified(self.settings.db_path, task.id)
            logger.info("Delivered result for task #%d to chat_id=%d", task.id, task.chat_id)
        except Exception:
            logger.exception("Failed to deliver result for task #%d", task.id)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start polling and result-delivery loop (blocking)."""
        logger.info("Telegram bot starting…")
        self.app.run_polling()
