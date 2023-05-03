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
from travian.bot_functions.example import TravianBotExampleFunction

from .browser import Browser
from pyppeteer.browser import Browser as PyppeteerBrowser

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyppeteer.page import Page

import logging

logger = logging.getLogger(__name__)


class TravianBot:

    def __init__(self, server_url: str, event_loop: Optional[asyncio.AbstractEventLoop] = None):
        self.server_url = build_server_url(server_url)
        self.config = Config()
        self.data = Data()
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

        await TravianBotScreenshot(self, 'dorf1.php', 'start').schedule()

        if self.config.farming_list.is_enabled:
            await TravianBotFarmingList(self).schedule()

        # await TravianBotLogout(self).schedule()

    async def loop(self):
        await self.scheduler.loop()

        if self.is_stopping:
            await self.stop()

    async def connect(self) -> 'Browser':
        if not self.browser or not self.browser.is_connected:
            self.browser = await self.__connect_browser()

            logger.info('Started')

            def disconnected():
                logger.info('Disconnected')

                # if not self.is_stopped or self.is_stopping:
                #     self._event_loop.create_task(self.__connect_browser())

            self.browser.on(PyppeteerBrowser.Events.Disconnected, disconnected)

        return self.browser

    async def __connect_browser(self) -> 'Browser':
        self.browser = await start_browser(headless=False, event_loop=self._event_loop, chrome_path=self.config.chrome_path)
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
            await self.scheduler.run(TravianBotLogout(self, retry_on_page_error=False), reschedule_on_error=False)

            if self.browser_is_connected:
                await self.browser.close()

        self.data.save()

        logger.info('Stopped')

    def kill(self):
        logger.warning('KILL')

        if self.browser:
            self.browser.terminate()
            self.browser = None

        self.data.save()

        self._event_loop.stop()

        logger.warning('KILLED')

    async def go_to_server_url(self, logger: logging.Logger, page_url: str = '',
                               check_login=True, new_tab=False, log=True, retry_seconds: Optional[int] = 2) -> 'Page':
        return await self.__get_server_page(Browser.go, logger, page_url, check_login, new_tab, log, retry_seconds)

    async def get_current_page_or_go_to_server_url(self, logger: logging.Logger, page_url: str = '',
                                                   check_login=True, new_tab=False, log=True, retry_seconds: Optional[int] = 2) -> 'Page':
        return await self.__get_server_page(Browser.get_current_page_or_go, logger, page_url, check_login, new_tab, log, retry_seconds)

    async def __get_server_page(self, get_page_or_go, logger: logging.Logger, page_url: str,
                                check_login: bool, new_tab: bool, log: bool, retry_seconds: Optional[int]) -> 'Page':
        browser = await self.connect()

        url = self.get_server_url(page_url)
        page: 'Page' = await get_page_or_go(browser, logger, url, new_tab=new_tab, log=log, retry_seconds=retry_seconds)

        if check_login and await TravianBotLogin.is_login_page(self.server_url, page):
            await self.scheduler.run(TravianBotLogin(self, page))

            if page.url != url:
                await get_page_or_go(browser, logger, url, new_tab=new_tab, log=log, retry_seconds=retry_seconds)

        return page

    def get_server_url(self, page_url: str) -> str:
        if page_url.startswith('/'):
            page_url = page_url[1:]
        return self.server_url + (page_url or '')


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
        __handle_exception(exception, stacktrace=False)

    event_loop.set_exception_handler(handle_exception_loop)


def __handle_exception(e: Optional[BaseException], stacktrace=True):
    if e is not None:
        if isinstance(e, (KeyboardInterrupt, CancelledError, asyncio.exceptions.CancelledError)):
            logger.debug(e.__class__.__name__)
        else:
            msg = str(e)
            if msg != 'This event loop is already running':
                exc_info = (e or True) if stacktrace else None
                logger.error(f'[{e.__class__.__name__}] {msg}', exc_info=exc_info)


def handle_interrupt(bot: TravianBot):
    signal_count = 0

    async def handle_signal():
        nonlocal signal_count
        signal_count += 1
        logger.debug(f'SIGNAL {signal_count}')
        if signal_count > 2:
            bot.kill()
        elif not bot.is_stopped:
            await bot.stop()

    def handle_signal_sync(signal_name):
        def handle_signal_async():
            asyncio.run_coroutine_threadsafe(handle_signal(), bot._event_loop)

        def wrap_handle_signal(_signal, _frame):
            logger.warn(f'Received {signal_name}. Waiting to stop...')
            # bot._event_loop.create_task(handle_signal())
            bot._event_loop.run_in_executor(None, handle_signal_async)

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
