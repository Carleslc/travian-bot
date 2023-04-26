import os.path

import logging

import asyncio

from pathlib import Path

from settings import console_log

from pyppeteer import launch
from pyppeteer.page import Page

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyppeteer.page import ConsoleMessage, ElementHandle
    from pyppeteer.browser import Browser as PyppeteerBrowser

logger = logging.getLogger(__name__)
logger_console = logging.getLogger(__name__ + '.console')

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36'

DEFAULT_BROWSER_ARGS = ['--mute-audio']  # '--no-sandbox'


class Browser:

    def __init__(self, headless=True, headers={}):
        self.headless = headless
        self.__headers = headers
        self.__browser = None  # type: ignore (not connected yet)

    @property
    def is_connected(self):
        return self.__browser is not None

    async def connect(self, width=1920, height=1080, args: list[str] = DEFAULT_BROWSER_ARGS):
        if not self.headless:
            args.append(f'--window-size={width},{height}')
            args.append('--start-maximized')  # --start-fullscreen

        self.__browser: 'PyppeteerBrowser' = await launch(
            headless=self.headless,
            defaultViewport={'width': width, 'height': height},
            args=args)

        logger.info('Browser Connected')

    async def close(self):
        if self.is_connected:
            self.__browser.remove_all_listeners()

            await self.__browser.close()

            logger.info('Browser Closed')

    async def go(self, logger: logging.Logger, url: str, new_tab=False, log=False) -> Page:
        if not self.is_connected:
            raise ConnectionError('Browser is not connected')

        logger.debug(f'Loading:  {url}')

        if new_tab:
            page = await self.__browser.newPage()

            await page.setUserAgent(USER_AGENT)

            await page.setExtraHTTPHeaders(self.__headers)
        else:
            page = (await self.__browser.pages())[0]

        if log:
            Browser.attach_console(page)

        page.remove_all_listeners(Page.Events.Load)

        await page.goto(url)

        logger.debug(f'Loaded:   {page.url}')

        def loaded():
            logger.debug(f'Navigate: {page.url}')

        page.on(Page.Events.Load, loaded)

        return page

    async def click(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, **kwargs):
        logger.debug(f'Click:\t{clickTitle}')

        await page.waitForSelector(clickSelector)

        return await page.click(clickSelector, **kwargs)

    async def click_go(self, logger: logging.Logger, page: Page, clickTitle: str, clickSelector: str, timeout: int = 30000, **kwargs):
        await asyncio.gather(
            self.click(logger, page, clickTitle, clickSelector, **kwargs),
            page.waitForNavigation(timeout=timeout)
        )

    async def type(self, logger: logging.Logger, page: Page, inputTitle: str, inputSelector: str, inputContent: str, obfuscate: Optional[str] = None, **kwargs):
        logger.debug(f"Type:\t{inputTitle} -> {f'({obfuscate})' if obfuscate else inputContent}")

        await page.waitForSelector(inputSelector)

        await page.type(inputSelector, inputContent, **kwargs)

    async def wait(self, logger: logging.Logger, page: Page, milliseconds: int, **kwargs):
        logger.debug(f'Waiting for {milliseconds} ms')

        await page.waitFor(milliseconds, **kwargs)

    async def screenshot(self, logger: logging.Logger, page: Page, filename: str, delay: int = 0, **kwargs):
        if delay:
            await self.wait(logger, page, delay)

        logger.debug(f'Screenshot ({filename}): {page.url}')

        screenshots_dir = Path('screenshots')
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, filename)

        return await page.screenshot(path=screenshot_path, type='png', fullPage=True, **kwargs)

    async def text_content(self, page: Page, element: 'ElementHandle'):
        return await page.evaluate('(element) => element.textContent', element)

    def on(self, event: str, handler):
        self.__browser.on(event, lambda *args: asyncio.ensure_future(handler(*args)))

    @staticmethod
    def on_page_async(page: Page, event: str, async_handler):
        page.on(event, lambda *args: asyncio.ensure_future(async_handler(*args)))

    @staticmethod
    def attach_console(page: Page):
        async def log_console_message(msg: 'ConsoleMessage'):
            for arg in msg.args:
                console_log(logger_console, msg.type, str(await arg.jsonValue()))

        Browser.on_page_async(page, Page.Events.Console, log_console_message)


async def start_browser(headless=True, width=1440, height=900, args: list[str] = DEFAULT_BROWSER_ARGS):
    browser = Browser(headless=headless)
    await browser.connect(width=width, height=height, args=args)
    return browser
