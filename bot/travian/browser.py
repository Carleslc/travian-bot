import os.path

import asyncio

from pathlib import Path
from subprocess import Popen

from settings import console_log

import pyppeteer
from pyppeteer.page import Page
from pyppeteer.errors import PyppeteerError, PageError
from pyppeteer.browser import Browser as PyppeteerBrowser

from pyppeteer_stealth import stealth

from typing import Optional, TypeVar, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pyppeteer.page import ConsoleMessage, ElementHandle

import logging

logger = logging.getLogger(__name__)
logger_console = logging.getLogger(__name__ + '.console')
browser_logger = logger

BrowserEvent = TypeVar('BrowserEvent', str, type(PyppeteerBrowser.Events))
PageEvent = TypeVar('PageEvent', str, type(Page.Events))

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'

DEFAULT_BROWSER_ARGS = ['--mute-audio']
HEADLESS_BROWSER_ARGS = ['--disable-setuid-sandbox']  # '--disable-features=site-per-process'


class Browser:

    def __init__(self, headless=True, headers={}, width=1920, height=1080,
                 args: list[str] = DEFAULT_BROWSER_ARGS, event_loop: Optional[asyncio.AbstractEventLoop] = None,
                 chrome_path: Optional[str] = None):
        self.headless = headless
        self.headers = headers
        self.width = width
        self.height = height
        self.args = args
        self.__browser: Optional[PyppeteerBrowser] = None
        self.__executable_path = chrome_path if chrome_path else None
        self.__event_loop = event_loop

        self.args.append(f'--window-size={width},{height}')

        if headless:
            self.args.extend(HEADLESS_BROWSER_ARGS)
        else:
            self.args.append('--start-maximized')  # --start-fullscreen

    @property
    def is_google_chrome(self) -> bool:
        return self.__executable_path is not None and 'Google Chrome' in self.__executable_path

    @property
    def is_connected(self) -> bool:
        return self.__browser is not None

    @property
    def _event_loop(self) -> asyncio.AbstractEventLoop:
        return self.__event_loop or asyncio.get_event_loop()

    async def connect(self) -> PyppeteerBrowser:
        if self.__browser is None:
            logger.debug('Connecting...')

            if self.__browser is None:
                self.__browser = await pyppeteer.launch(
                    headless=self.headless,
                    defaultViewport={'width': self.width, 'height': self.height},
                    args=self.args,
                    handleSIGINT=False,
                    handleSIGTERM=False,
                    loop=self._event_loop,
                    executablePath=self.__executable_path,
                    dumpio=False)

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

        page = await self.get_current_page() if not new_tab else None

        if not page:
            page = await browser.newPage()

            await page.setUserAgent(USER_AGENT)

            await page.setExtraHTTPHeaders(self.headers)

            await stealth(page)

        if log:
            Browser.attach_console(page)

        page.remove_all_listeners(Page.Events.Load)

        page.remove_all_listeners(Page.Events.Error)
        page.remove_all_listeners(Page.Events.PageError)

        def on_browser_error(e: PyppeteerError):
            browser_logger.warning(f'{e.__class__.__name__}: {page.url}\n{e}')
            asyncio.run_coroutine_threadsafe(self.disconnect(), self._event_loop)

        def on_page_error(e: PageError):
            ignore = False
            error_msg = str(e)
            if 'TypeError' in error_msg:
                error_msg = error_msg.split('\n')[0]
                ignore = 'e.indexOf is not a function' in error_msg
            if not ignore:
                browser_logger.warning(f'{e.__class__.__name__}: {page.url}\n{error_msg}')

        page.on(Page.Events.Error, on_browser_error)
        page.on(Page.Events.PageError, on_page_error)

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

        logger.info(f'Loaded:   {page.url}')

        def loaded():
            browser_logger.debug(f'Navigate: {page.url}')

        page.on(Page.Events.Load, loaded)

        return page

    async def get_current_page(self) -> Optional[Page]:
        page = None
        if self.__browser:
            try:
                page = (await self.__browser.pages())[0]
            except:
                pass
        return page

    async def get_current_page_or_go(self, logger: logging.Logger, url: str, **kwargs) -> Page:
        page = await self.get_current_page()

        if not page:
            page = await self.go(logger, url, **kwargs)

        return page

    async def click(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, **kwargs):
        await page.waitForSelector(clickSelector, timeout=kwargs.get('timeout', 30000))

        logger.info(f'Click:\t{clickTitle}')

        return await page.click(clickSelector, **kwargs)

    async def click_element(self, logger: logging.Logger, element: 'ElementHandle', clickTitle: str, **kwargs):
        logger.info(f'Click:\t{clickTitle}')

        return await element.click(**kwargs)

    async def click_go(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, timeout: int = 30000, **kwargs):
        clickTimeout = min(1000, timeout - 1000)

        await asyncio.gather(
            self.click(logger, page, clickTitle, clickSelector, timeout=clickTimeout, **kwargs),
            page.waitForNavigation(timeout=timeout)
        )

    async def type(self, logger: logging.Logger, page: Page, inputTitle: str, inputSelector: str, inputContent: str, obfuscate: Optional[str] = None, **kwargs):
        logger.info(f"Type:\t{inputTitle} -> {f'({obfuscate})' if obfuscate else inputContent}")

        await page.waitForSelector(inputSelector)

        await page.querySelectorEval(inputSelector, '(inputElement) => inputElement.value = ""')  # clear input

        await page.type(inputSelector, inputContent, **kwargs)

    async def text_content(self, page: Page, element: 'ElementHandle') -> Optional[str]:
        text = await page.evaluate('(element) => element.textContent', element)
        return text.strip() if text else None

    async def attribute(self, page: Page, element: 'ElementHandle', attribute: str) -> Optional[str]:
        attr = await page.evaluate('(element, attribute) => element.getAttribute(attribute)', element, attribute)
        return attr.strip() if attr else None

    async def wait(self, logger: logging.Logger, page: Page, milliseconds: int, **kwargs):
        if milliseconds > 0:
            logger.debug(f'Waiting for {milliseconds} ms')

            await page.waitFor(milliseconds, **kwargs)

    async def screenshot(self, logger: logging.Logger, page: Page, filepath: str, delay_ms: int = 0, **kwargs):
        await self.wait(logger, page, delay_ms)

        logger.info(f'Screenshot ({filepath}): {page.url}')

        screenshots_dir = Path('screenshots')
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, filepath)

        full_page = kwargs.get('fullPage', not self.is_google_chrome)

        return await page.screenshot(path=screenshot_path, type='png', fullPage=full_page, **kwargs)

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


async def start_browser(headless=True, width=1440, height=900, args: list[str] = DEFAULT_BROWSER_ARGS,
                        event_loop: Optional[asyncio.AbstractEventLoop] = None, chrome_path: Optional[str] = None) -> Browser:
    browser = Browser(headless=headless, width=width, height=height,
                      args=args, event_loop=event_loop, chrome_path=chrome_path)
    await browser.connect()
    return browser
