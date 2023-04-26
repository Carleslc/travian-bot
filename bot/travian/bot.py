import os

import asyncio

from .config import load_config_file
from .browser import start_browser
from .task_queue import TaskQueue

from travian.bot_functions.login import TravianBotLogin
from travian.bot_functions.logout import TravianBotLogout
from travian.bot_functions.screenshot import TravianBotScreenshot

from pyppeteer.browser import Browser as PyppeteerBrowser

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .browser import Browser

import logging

logger = logging.getLogger(__name__)


class TravianBot:

    def __init__(self, server_url: str):
        self.server_url = build_server_url(server_url)
        self.browser: Optional[Browser] = None
        self.config: Optional[dict] = None
        self.tasks_queue = TaskQueue()

    async def configure(self):
        if self.config is None:
            self.load_config()

        self.tasks_queue.append(TravianBotScreenshot(self))

    def load_config(self):
        self.config = load_config_file()

    async def loop(self):
        await self.tasks_queue.loop()

    async def connect(self) -> 'Browser':
        if not self.browser:
            self.browser = await start_browser(headless=False)

            logger.info('Started')

            def disconnected():
                logger.info('Disconnected')
                self.browser = None

            self.browser.on(PyppeteerBrowser.Events.Disconnected, disconnected)

        return self.browser

    async def stop(self):
        if self.browser:
            await TravianBotLogout(self).run()

            await self.browser.close()

            logger.info('Stopped')

    async def go_to_server_url(self, logger: logging.Logger, page_url: str = '', new_tab=False, log=True):
        browser = await self.connect()

        url = self.server_url + (page_url or '')
        page = await browser.go(logger, url, new_tab=new_tab, log=log)

        if page_url != TravianBotLogout.LOGOUT_URL:
            await TravianBotLogin.check_logged_in(self, page)

        return page


def build_server_url(url: str) -> str:
    HTTPS_PROTOCOL = 'https://'
    if not url.startswith(HTTPS_PROTOCOL):
        url = HTTPS_PROTOCOL + url
    if not url.endswith('/'):
        url += '/'
    return url


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
