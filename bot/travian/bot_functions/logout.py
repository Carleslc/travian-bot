from travian.bot_functions import TravianBotFunction

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot

import logging

logger = logging.getLogger(__name__)


class TravianBotLogout(TravianBotFunction):

    LOGOUT_URL = 'logout'

    def __init__(self, bot: 'TravianBot', retry_on_error=True):
        super().__init__(bot)
        self.retry_on_error = retry_on_error

    async def run(self):
        if self.browser:
            retry_seconds = 2 if self.retry_on_error else None
            logout_page = await self.go_to_server_url(logger, TravianBotLogout.LOGOUT_URL, check_login=False, log=False, retry_seconds=retry_seconds)

            if self.browser_is_connected and not self.browser.headless:
                await self.browser.wait(logger, logout_page, 1000)
