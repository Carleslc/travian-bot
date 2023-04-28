from travian.bot_functions import TravianBotFunction

import logging

logger = logging.getLogger(__name__)


class TravianBotExampleFunction(TravianBotFunction):

    async def run(self):
        logger.debug('EXAMPLE')

    async def schedule(self):
        await self.bot.scheduler.append(self, interval_seconds=5)
