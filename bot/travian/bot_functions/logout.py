from travian.bot_functions import TravianBotFunction

import logging

logger = logging.getLogger(__name__)


class TravianBotLogout(TravianBotFunction):

    LOGOUT_URL = 'logout'

    async def run(self):
        if self.browser:
            logout_page = await self.go_to_server_url(logger, TravianBotLogout.LOGOUT_URL, log=False)

            await self.browser.wait(logger, logout_page, 1000)
