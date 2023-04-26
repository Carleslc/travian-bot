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

    def __init__(self, headless=False, headers={}):
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
            await self.__browser.close()

            logger.info('Browser Closed')

    async def go(self, url: str, newTab=False, log=False) -> Page:
        if not self.is_connected:
            raise ConnectionError('Browser is not connected')

        logger.debug(f'Loading:\t{url}')

        if newTab:
            page = await self.__browser.newPage()

            await page.setUserAgent(USER_AGENT)

            await page.setExtraHTTPHeaders(self.__headers)
        else:
            page = (await self.__browser.pages())[0]

        if log:
            Browser.attach_console(page)

        await page.goto(url)

        logger.debug(f'Loaded:\t{page.url}')

        return page

    async def click(self, page: Page, clickTitle: str, clickSelector: str, **kwargs):
        logger.debug(f'Click:\t{clickTitle}')

        await page.waitForSelector(clickSelector)

        return await page.click(clickSelector, **kwargs)

    async def click_go(self, page: Page, clickTitle: str, clickSelector: str, timeout: int = 30000, **kwargs):
        before_url = page.url

        await asyncio.gather(
            self.click(page, clickTitle, clickSelector, **kwargs),
            page.waitForNavigation(timeout=timeout)
        )

        after_url = page.url

        if before_url != after_url:
            logger.debug(f'Navigation:\t{after_url}')

    async def type(self, page: Page, inputTitle: str, inputSelector: str, inputContent: str, obfuscate: Optional[str] = None, **kwargs):
        logger.debug(f"Type:\t{inputTitle} -> {f'({obfuscate})' if obfuscate else inputContent}")

        await page.waitForSelector(inputSelector)

        await page.type(inputSelector, inputContent, **kwargs)

    async def wait(self, page: Page, milliseconds: int, **kwargs):
        logger.debug(f'Waiting for {milliseconds} ms')

        await page.waitFor(milliseconds, **kwargs)

    async def screenshot(self, page: Page, filename: str, delay: int = 0, **kwargs):
        if delay:
            await self.wait(page, delay)

        logger.debug(f'Screenshot ({filename}): {page.url}')

        screenshots_dir = Path('screenshots')
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, filename)

        return await page.screenshot(path=screenshot_path, type='png', fullPage=True, **kwargs)

    async def text_content(self, page: Page, element: 'ElementHandle'):
        return await page.evaluate('(element) => element.textContent', element)

    @staticmethod
    def attach_console(page: Page):
        async def log_console_message(msg: 'ConsoleMessage'):
            for arg in msg.args:
                console_log(logger_console, msg.type, str(await arg.jsonValue()))

        def console_handler(msg):
            asyncio.ensure_future(log_console_message(msg))

        page.on(Page.Events.Console, console_handler)


async def start_browser(headless=False, width=1440, height=900, args: list[str] = DEFAULT_BROWSER_ARGS):
    browser = Browser(headless=headless)
    await browser.connect(width=width, height=height, args=args)
    return browser
