import asyncio

from travian.bot_functions import TravianBotFunction

from pyppeteer.errors import PyppeteerError

import logging

logger = logging.getLogger(__name__)


class TravianBotExampleFunction(TravianBotFunction):

    async def run(self):
        logger.debug('EXAMPLE')

        await asyncio.sleep(2)

        raise PyppeteerError('FAILED EXAMPLE')

    async def schedule(self):
        await self.bot.scheduler.append(self, interval_seconds=20, blocking=False)
