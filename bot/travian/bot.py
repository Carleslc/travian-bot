import os
import signal
import asyncio

from concurrent.futures import CancelledError

from .data import Data
from .config import Config
from .browser import start_browser
from .task_scheduler import TaskScheduler

from travian.bot_functions.login import TravianBotLogin
from travian.bot_functions.logout import TravianBotLogout
from travian.bot_functions.screenshot import TravianBotScreenshot
from travian.bot_functions.farming import TravianBotFarmingList

from pyppeteer.browser import Browser as PyppeteerBrowser

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .browser import Browser

    from pyppeteer.page import Page

import logging

logger = logging.getLogger(__name__)


class TravianBot:

    def __init__(self, server_url: str, event_loop: Optional[asyncio.AbstractEventLoop] = None):
        self.server_url = build_server_url(server_url)
        self.config: Config = Config()
        self.data: Data = Data()
        self.browser: Optional[Browser] = None
        self._stop_task: Optional[asyncio.Task] = None
        self.__event_loop = event_loop
        self.scheduler = TaskScheduler(self)

    @property
    def _event_loop(self):
        return self.__event_loop or asyncio.get_running_loop()

    async def configure(self):
        await self.scheduler.clear()

        self.config.load()
        self.data.load()

        # await TravianBotExampleFunction(self).schedule()

        await TravianBotScreenshot(self, 'start').schedule()

        if self.config.farming_list.is_enabled:
            await TravianBotFarmingList(self).schedule()

        # await TravianBotLogout(self).schedule()

    async def loop(self):
        await self.scheduler.loop()

    async def connect(self) -> 'Browser':
        if not self.browser or not self.browser.is_connected:
            self.browser = await start_browser(headless=False, event_loop=self._event_loop)

            logger.info('Started')

            def disconnected():
                logger.info('Disconnected')

            self.browser.on(PyppeteerBrowser.Events.Disconnected, disconnected)

        return self.browser

    @property
    def browser_is_connected(self) -> bool:
        return self.browser is not None and self.browser.is_connected

    @property
    def is_stopping(self) -> bool:
        return self._stop_task is not None and not self._stop_task.done()

    @property
    def is_stopped(self) -> bool:
        return self._stop_task is not None and self._stop_task.done()

    async def stop(self):
        if not self.is_stopped:
            if self._stop_task is None:
                self._stop_task = asyncio.ensure_future(self.__stop())
            await self._stop_task

    async def __stop(self):
        logger.debug('Stopping...')

        await self.scheduler.clear(cancel_running_tasks=True)

        if self.browser:
            await self.scheduler.run(TravianBotLogout(self, retry_on_error=False))

            if self.browser_is_connected:
                await self.browser.close()

        logger.info('Stopped')

    async def go_to_server_url(self, logger: logging.Logger, page_url: str = '',
                               check_login=True, new_tab=False, log=True, retry_seconds: Optional[int] = 2) -> 'Page':
        browser = await self.connect()

        url = self.server_url + (page_url or '')
        page = await browser.go(logger, url, new_tab=new_tab, log=log, retry_seconds=retry_seconds)

        if check_login:
            await TravianBotLogin.check_logged_in(self, page)

        return page


def build_server_url(url: str) -> str:
    HTTPS_PROTOCOL = 'https://'
    if not url.startswith(HTTPS_PROTOCOL):
        url = HTTPS_PROTOCOL + url
    if not url.endswith('/'):
        url += '/'
    return url


def handle_exceptions(event_loop: asyncio.AbstractEventLoop):
    # https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler
    def handle_exception_loop(_: asyncio.AbstractEventLoop, context: dict):
        exception = context.get('exception')
        if exception is None:
            exception = context['message']
        __handle_exception(exception)

    event_loop.set_exception_handler(handle_exception_loop)


def __handle_exception(e: Optional[BaseException]):
    if e is not None:
        if isinstance(e, (KeyboardInterrupt, CancelledError, asyncio.exceptions.CancelledError)):
            logger.debug(e.__class__.__name__)
        else:
            msg = str(e)
            if msg != 'This event loop is already running':
                logger.error(f'[{e.__class__.__name__}] {msg}')


def handle_interrupt(bot: TravianBot):
    async def handle_signal():
        if not bot.is_stopped:
            await bot.stop()
        else:
            bot._event_loop.call_soon_threadsafe(bot._event_loop.stop)

    def handle_signal_sync(signal_name):
        def wrap_handle_signal(_signal, _frame):
            logger.warn(f'Received {signal_name}. Waiting to stop...')
            bot._event_loop.create_task(handle_signal())

        return wrap_handle_signal

    signal.signal(signal.SIGINT, handle_signal_sync('SIGINT'))
    signal.signal(signal.SIGTERM, handle_signal_sync('SIGTERM'))


def start_travian_bot():
    server_url = os.getenv('TRAVIAN_SERVER_URL')

    if not server_url:
        logger.error('Missing TRAVIAN_SERVER_URL')
        exit(1)

    event_loop = asyncio.get_event_loop()

    async def start():
        handle_exceptions(event_loop)

        bot = TravianBot(server_url, event_loop)

        handle_interrupt(bot)

        try:
            await bot.configure()
            await bot.loop()
        finally:
            await bot.stop()

    try:
        event_loop.run_until_complete(start())
    except BaseException as e:
        __handle_exception(e)
