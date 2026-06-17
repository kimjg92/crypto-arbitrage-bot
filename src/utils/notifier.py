import asyncio
from src.core.logger import setup_logger

logger = setup_logger()

class Notifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

    async def send(self, message: str):
        if not self.enabled:
            return
        try:
            from telegram import Bot
            bot = Bot(token=self.bot_token)
            await bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            logger.warning(f"텔레그램 알림 실패: {e}")
