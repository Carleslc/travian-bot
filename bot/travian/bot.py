import os

import logging

import asyncio

from .browser import start_browser
from .utils import build_server_url
from .errors import AuthenticationError

from pyppeteer.errors import TimeoutError

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .browser import Browser
    from pyppeteer.page import Page

logger = logging.getLogger(__name__)


class TravianBot:

    LOGIN_URL = 'login.php'
    LOGOUT_URL = 'logout'

    def __init__(self, server_url: str):
        self.server_url = build_server_url(server_url)
        self.browser: Browser = None  # type: ignore (not connected yet)

    async def connect(self):
        if self.browser is None:
            self.browser = await start_browser()

            logger.info('Started')

    async def loop(self):
        page = await self.go_to_server_url()

        await self.browser.screenshot(page, 'screenshot.png', delay=2000)

    async def stop(self):
        if self.browser and self.browser.is_connected:
            await self.go_to_server_url(TravianBot.LOGOUT_URL)
            await self.browser.close()

            logger.info('Stopped')

    async def __check_logged_in(self, page: 'Page'):
        if page.url == self.server_url or page.url.endswith(TravianBot.LOGIN_URL):
            is_login_page = (await page.querySelector('body.login')) is not None
        else:
            is_login_page = False

        if is_login_page:
            await self.__login(page)

    async def __login(self, page: 'Page'):
        email, password = get_credentials()

        email_input = '#loginForm > tbody > tr.account > td:nth-child(2) > input'
        await self.browser.type(page, 'Email', email_input, email, 'email')

        password_input = '#loginForm > tbody > tr.pass > td:nth-child(2) > input'
        await self.browser.type(page, 'Password', password_input, password, 'password')

        try:
            login_button = '#loginForm > tbody > tr.loginButtonRow > td:nth-child(2) > button[value=Login]'
            await self.browser.click_go(page, 'Login Button', login_button, timeout=5000)

            logger.info('Logged in')
        except TimeoutError as e:
            login_error_element = await page.querySelector('#error')

            login_error = await self.browser.text_content(page, login_error_element) if login_error_element else None

            if login_error:
                raise AuthenticationError(login_error)
            else:
                raise e

    async def go_to_server_url(self, pageUrl: str = ''):
        await self.connect()

        url = self.server_url + (pageUrl or '')
        page = await self.browser.go(url, log=True)

        if pageUrl != TravianBot.LOGOUT_URL:
            await self.__check_logged_in(page)

        return page


def get_credentials() -> tuple[str, str]:
    email = os.getenv('TRAVIAN_EMAIL')

    if not email:
        raise AuthenticationError('Missing TRAVIAN_EMAIL')

    password = os.getenv('TRAVIAN_PASSWORD')

    if not password:
        raise AuthenticationError('Missing TRAVIAN_PASSWORD')

    return email, password


def start_travian_bot():
    server_url = os.getenv('TRAVIAN_SERVER_URL')

    if not server_url:
        logger.error('Missing TRAVIAN_SERVER_URL')
    else:
        async def start():
            bot = TravianBot(server_url)

            try:
                await bot.loop()
            except Exception as e:
                logger.error(e)
            finally:
                await bot.stop()

        asyncio.get_event_loop().run_until_complete(start())
