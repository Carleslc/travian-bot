import os.path

import asyncio

from pathlib import Path
from subprocess import Popen

from settings import console_log

from pyppeteer import launch
from pyppeteer.page import Page
from pyppeteer.errors import PyppeteerError
from pyppeteer.browser import Browser as PyppeteerBrowser

from pyppeteer_stealth import stealth

from typing import Optional, TypeVar, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pyppeteer.page import ConsoleMessage, ElementHandle

import logging

logger = logging.getLogger(__name__)
logger_console = logging.getLogger(__name__ + '.console')

BrowserEvent = TypeVar('BrowserEvent', str, type(PyppeteerBrowser.Events))
PageEvent = TypeVar('PageEvent', str, type(Page.Events))

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'

DEFAULT_BROWSER_ARGS = ['--mute-audio', '--disable-features=IsolateOrigins',
                        '--disable-site-isolation-trials']  # --no-sandbox


class Browser:

    def __init__(self, headless=True, headers={}, width=1920, height=1080,
                 args: list[str] = DEFAULT_BROWSER_ARGS, event_loop: Optional[asyncio.AbstractEventLoop] = None):
        self.headless = headless
        self.headers = headers
        self.width = width
        self.height = height
        self.args = args
        self.__browser: Optional[PyppeteerBrowser] = None
        self.__event_loop = event_loop

        if not headless:
            self.args.append(f'--window-size={width},{height}')
            self.args.append('--start-maximized')  # --start-fullscreen

    @property
    def _event_loop(self) -> asyncio.AbstractEventLoop:
        return self.__event_loop or asyncio.get_event_loop()

    @property
    def is_connected(self):
        return self.__browser is not None

    async def connect(self) -> PyppeteerBrowser:
        if self.__browser is None:
            logger.debug('Connecting...')

            self.__browser = await launch(
                headless=self.headless,
                defaultViewport={'width': self.width, 'height': self.height},
                args=self.args,
                handleSIGINT=False,
                handleSIGTERM=False,
                loop=self._event_loop)

            logger.debug('Connected')

            def disconnected():
                logger.debug('Disconnected')
                self.__browser = None

            self.on(PyppeteerBrowser.Events.Disconnected, disconnected)

        return self.__browser

    async def disconnect(self):
        if self.__browser:
            await self.__browser.disconnect()

    async def close(self):
        if self.__browser:
            logger.debug('Closing browser...')

            await self.__browser.close()

            self.terminate()

            logger.debug('Closed')

    def terminate(self):
        if self.__browser:
            cast(Popen, self.__browser.process).terminate()

    async def go(self, logger: logging.Logger, url: str, new_tab=False, log=False, retry_seconds: Optional[int] = 2) -> Page:
        browser = await self.connect()

        logger.debug(f'Loading:  {url}')

        pages = await browser.pages()

        new_tab = new_tab or not pages

        if new_tab:
            page = await browser.newPage()

            await page.setUserAgent(USER_AGENT)

            await page.setExtraHTTPHeaders(self.headers)

            await stealth(page)
        else:
            page = pages[0]

        if log:
            Browser.attach_console(page)

        page.remove_all_listeners(Page.Events.Load)

        def on_page_error(e: Exception):
            logger.warning(f'{e.__class__.__name__}: {page.url}\n{e}')
            asyncio.run_coroutine_threadsafe(self.disconnect(), self._event_loop)
            raise e

        page.on(Page.Events.PageError, on_page_error)
        page.on(Page.Events.Error, on_page_error)

        try:
            await page.goto(url)
        except (PyppeteerError, asyncio.InvalidStateError) as e:
            error_msg = f'[{e.__class__.__name__}] {e}'
            if retry_seconds is not None:
                if retry_seconds > 0:
                    error_msg += f' >>> Retrying in {retry_seconds} seconds...'
                elif retry_seconds == 0:
                    error_msg += f' >>> Retrying...'
                else:
                    retry_seconds = None
            logger.warning(error_msg)
            if retry_seconds is not None and retry_seconds > 0:
                await asyncio.sleep(retry_seconds)
            if retry_seconds is not None:
                return await self.go(logger, url, new_tab, log, retry_seconds)
            raise e

        logger.debug(f'Loaded:   {page.url}')

        def loaded():
            logger.debug(f'Navigate: {page.url}')

        page.on(Page.Events.Load, loaded)

        return page

    async def click(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, **kwargs):
        await page.waitForSelector(clickSelector)

        logger.debug(f'Click:\t{clickTitle}')

        return await page.click(clickSelector, **kwargs)

    async def click_element(self, logger: logging.Logger, element: 'ElementHandle', clickTitle: str, **kwargs):
        logger.debug(f'Click:\t{clickTitle}')

        return await element.click(**kwargs)

    async def click_go(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, timeout: int = 30000, **kwargs):
        await asyncio.gather(
            self.click(logger, page, clickTitle, clickSelector, **kwargs),
            page.waitForNavigation(timeout=timeout)
        )

    async def type(self, logger: logging.Logger, page: Page, inputTitle: str, inputSelector: str, inputContent: str, obfuscate: Optional[str] = None, **kwargs):
        logger.debug(f"Type:\t{inputTitle} -> {f'({obfuscate})' if obfuscate else inputContent}")

        await page.waitForSelector(inputSelector)

        await page.type(inputSelector, inputContent, **kwargs)

    async def text_content(self, page: Page, element: 'ElementHandle') -> Optional[str]:
        text = await page.evaluate('(element) => element.textContent', element)
        return text.strip() if text else None

    async def attribute(self, page: Page, element: 'ElementHandle', attribute: str) -> Optional[str]:
        attr = await page.evaluate('(element, attribute) => element.getAttribute(attribute)', element, attribute)
        return attr.strip() if attr else None

    async def wait(self, logger: logging.Logger, page: Page, milliseconds: int, **kwargs):
        logger.debug(f'Waiting for {milliseconds} ms')

        await page.waitFor(milliseconds, **kwargs)

    async def screenshot(self, logger: logging.Logger, page: Page, filepath: str, delay_ms: int = 0, **kwargs):
        if delay_ms:
            await self.wait(logger, page, delay_ms)

        logger.info(f'Screenshot ({filepath}): {page.url}')

        screenshots_dir = Path('screenshots')
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, filepath)

        return await page.screenshot(path=screenshot_path, type='png', fullPage=True, **kwargs)

    async def close_page(self, logger: logging.Logger, page: 'Page', delay_seconds: int = 0):
        if self.__browser:
            await self.wait(logger, page, delay_seconds * 1000)

            if len(await self.__browser.pages()) > 1:
                await page.close()

    def on(self, event: 'BrowserEvent', handler):
        if self.__browser:
            self.__browser.on(event, handler)

    def on_async(self, event: 'BrowserEvent', async_handler):
        self.on(event, lambda *args: asyncio.ensure_future(async_handler(*args)))

    @staticmethod
    def on_page(page: Page, event: 'PageEvent', handler):
        page.on(event, handler)

    @staticmethod
    def on_page_async(page: Page, event: 'PageEvent', async_handler):
        Browser.on_page(page, event, lambda *args: asyncio.ensure_future(async_handler(*args)))

    @staticmethod
    def attach_console(page: Page):
        async def log_console_message(msg: 'ConsoleMessage'):
            for arg in msg.args:
                console_log(logger_console, msg.type, str(await arg.jsonValue()))

        Browser.on_page_async(page, Page.Events.Console, log_console_message)


async def start_browser(headless=True, width=1440, height=900, args: list[str] = DEFAULT_BROWSER_ARGS, event_loop: Optional[asyncio.AbstractEventLoop] = None) -> Browser:
    browser = Browser(headless=headless, width=width, height=height,
                      args=args, event_loop=event_loop)
    await browser.connect()
    return browser
