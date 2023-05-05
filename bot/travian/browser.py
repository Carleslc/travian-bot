import os.path

import asyncio

from pathlib import Path

from settings import console_log

from pyppeteer.page import Page
from pyppeteer.launcher import Launcher
from pyppeteer.errors import PyppeteerError, PageError
from pyppeteer.browser import Browser as PyppeteerBrowser
from pyppeteer.chromium_downloader import current_platform

from pyppeteer_stealth import stealth

from typing import Optional, Union, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from pyppeteer.page import ConsoleMessage, ElementHandle

import logging

logger = logging.getLogger(__name__)
logger_console = logging.getLogger(__name__ + '.console')
browser_logger = logger

BrowserEvent = TypeVar('BrowserEvent', str, type(PyppeteerBrowser.Events))
PageEvent = TypeVar('PageEvent', str, type(Page.Events))

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36'

# https://peter.sh/experiments/chromium-command-line-switches/
# chrome://flags
# chrome://discards
# chrome://flags/#heuristic-memory-saver-mode
DEFAULT_BROWSER_ARGS = ['--enable-automation', '--mute-audio']
NON_HEADLESS_BROWSER_ARGS = ['--start-maximized']  # --start-fullscreen
HEADLESS_BROWSER_ARGS = ['--hide-scrollbars', '--disable-setuid-sandbox']


class Browser:

    def __init__(self, headless=True, headers={}, width=1920, height=1080,
                 args: list[str] = DEFAULT_BROWSER_ARGS, event_loop: Optional[asyncio.AbstractEventLoop] = None,
                 chrome_path: Optional[str] = None, user_data_dir: Optional[str] = '.chrome-settings/'):
        self.headless = headless
        self.headers = headers
        self.width = width
        self.height = height
        self.args = args
        self.__launcher: Optional[Launcher] = None
        self.__browser: Optional[PyppeteerBrowser] = None
        self.__executable_path = chrome_path if chrome_path else None
        self.__user_data_dir = user_data_dir
        self.__event_loop = event_loop

        self.args.append(f'--window-size={width},{height}')
        self.args.extend(HEADLESS_BROWSER_ARGS if headless else NON_HEADLESS_BROWSER_ARGS)

        if headless:
            if self.__executable_path:
                # chrome://inspect
                # https://developer.chrome.com/articles/new-headless/
                self.args.append('--headless=new')

            if current_platform().startswith('win'):
                self.args.append('--disable-gpu')

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

            if self.__launcher is None:
                if self.__executable_path:
                    headless_mode = False  # handle manually --headless=new in self.args
                else:
                    headless_mode = self.headless

                self.__launcher = Launcher(
                    headless=headless_mode,
                    defaultViewport={'width': self.width, 'height': self.height},
                    args=self.args,
                    handleSIGINT=False,
                    handleSIGTERM=False,
                    loop=self._event_loop,
                    executablePath=self.__executable_path,
                    userDataDir=self.__user_data_dir,
                    devtools=False,  # not headless_mode
                    dumpio=False)

            if self.__browser is None:
                self.__browser = await self.__launcher.launch()

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

            await self.terminate()

            logger.debug('Closed')

    async def terminate(self):
        if self.__launcher and not self.__launcher.chromeClosed:
            await self.__launcher.killChrome()

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

        session = await page.target.createCDPSession()
        await session.send('Page.enable')
        await session.send('Page.setWebLifecycleState', {'state': 'active'})

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
                browser_logger.warning(f'{e.__class__.__name__}: {page.url}\n{e}')

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

        await page.bringToFront()

        logger.info(f'Click:\t{clickTitle}')

        return await page.click(clickSelector, **kwargs)

    async def click_element(self, logger: logging.Logger, page: Page, element: 'ElementHandle', clickTitle: str, **kwargs):
        await page.bringToFront()

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

        await page.bringToFront()

        await page.querySelectorEval(inputSelector, '(inputElement) => inputElement.value = ""')  # clear input

        await page.type(inputSelector, inputContent, **kwargs)

    async def text_content(self, page: Page, element: Union['ElementHandle', str, None], timeout: int = 10000) -> Optional[str]:
        if isinstance(element, str):
            await page.waitForSelector(element, timeout=timeout)
            element = await page.querySelector(element)
        if element:
            text = await page.evaluate('(element) => element.textContent', element)
            if text:
                return text.strip()
        return None

    async def attribute(self, page: Page, element: Union['ElementHandle', str, None], attribute: str, timeout: int = 10000) -> Optional[str]:
        if isinstance(element, str):
            await page.waitForSelector(element, timeout=timeout)
            element = await page.querySelector(element)
        if element:
            attr = await page.evaluate('(element, attribute) => element.getAttribute(attribute)', element, attribute)
            if attr:
                return attr.strip()
        return None

    async def bounding_box(self, page: Page, element: 'ElementHandle') -> dict:
        return await page.evaluate("""(element) => {
                const { top, left, width, height } = element.getBoundingClientRect();
                return { top, left, width, height };
            }""", element)

    async def wait(self, logger: Optional[logging.Logger], page: Page, milliseconds: int, **kwargs):
        if milliseconds > 0:
            if logger:
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

    async def close_page(self, logger: Optional[logging.Logger], page: 'Page', delay_seconds: int = 0):
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
