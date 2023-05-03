from travian.bot_functions import TravianBotFunction

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot

    from pyppeteer.page import Page

import logging

logger = logging.getLogger(__name__)


class TravianBotScreenshot(TravianBotFunction):

    def __init__(self, bot: 'TravianBot', page_url: str, filename='screenshot'):
        super().__init__(bot)
        self.page_url = page_url
        self.file = f'{filename}.png'

    async def run(self):
        page = await self.go_to_server_url(logger, self.page_url)

        await self.screenshot(page, delay=2000)

    async def screenshot(self, page: 'Page', delay: int = 0):
        if not self.browser:
            raise ConnectionError('Cannot screenshot because browser is not connected')

        await self.browser.screenshot(logger, page, self.file, delay=delay)
