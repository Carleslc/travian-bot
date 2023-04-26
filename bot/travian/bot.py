import os

import logging

import asyncio

from collections import deque

from .browser import start_browser
from .utils import build_server_url

from travian.bot_functions.login import TravianBotLogin
from travian.bot_functions.logout import TravianBotLogout
from travian.bot_functions.screenshot import TravianBotScreenshot

from pyppeteer.browser import Browser as PyppeteerBrowser

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .browser import Browser

    from travian.bot_functions import TravianBotFunction

logger = logging.getLogger(__name__)


class TravianBot:

    def __init__(self, server_url: str):
        self.server_url = build_server_url(server_url)
        self.browser: Browser = None  # type: ignore (not connected yet)
        self.tasks_queue: deque['TravianBotFunction'] = deque([])
        self.current_task: Optional['TravianBotFunction'] = None

    async def configure(self):
        self.schedule(TravianBotScreenshot(self))

    def schedule(self, task: 'TravianBotFunction'):
        self.tasks_queue.append(task)

    async def loop(self):
        while len(self.tasks_queue) > 0:
            self.current_task = self.tasks_queue.popleft()
            await self.current_task.run()
        self.current_task = None

    async def connect(self):
        if self.browser is None:
            self.browser = await start_browser(headless=False)

            async def recover():
                logger.info('Reconnecting...')
                self.browser = None  # type: ignore (disconnected)
                await self.connect()
                if self.current_task:
                    await self.current_task.run()

            self.browser.on(PyppeteerBrowser.Events.Disconnected, recover)

            logger.info('Started')

    async def stop(self):
        if self.browser:
            await TravianBotLogout(self).run()

            await self.browser.close()

            self.browser = None  # type: ignore (disconnected)

            logger.info('Stopped')

    async def go_to_server_url(self, logger: logging.Logger, page_url: str = '', new_tab=False, log=True):
        await self.connect()

        url = self.server_url + (page_url or '')
        page = await self.browser.go(logger, url, new_tab=new_tab, log=log)

        if page_url != TravianBotLogout.LOGOUT_URL:
            await TravianBotLogin.check_logged_in(self, page)

        return page


def start_travian_bot():
    server_url = os.getenv('TRAVIAN_SERVER_URL')

    if not server_url:
        logger.error('Missing TRAVIAN_SERVER_URL')
    else:
        async def start():
            bot = TravianBot(server_url)

            try:
                await bot.configure()
                await bot.loop()
            except Exception as e:
                logger.error(e)
            finally:
                await bot.stop()

        asyncio.get_event_loop().run_until_complete(start())
