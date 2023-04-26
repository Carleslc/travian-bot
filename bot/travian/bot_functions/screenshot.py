from travian.bot_functions import TravianBotFunction

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyppeteer.page import Page

import logging

logger = logging.getLogger(__name__)


class TravianBotScreenshot(TravianBotFunction):

    async def run(self):
        page = await self.go_to_server_url(logger)

        await self.screenshot(page, delay=2000)

    async def screenshot(self, page: 'Page', delay: int = 0):
        await self.browser.screenshot(logger, page, 'screenshot.png', delay=delay)
