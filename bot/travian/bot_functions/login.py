import os

from travian.bot_functions import TravianBotFunction
from travian.errors import AuthenticationError

from pyppeteer.errors import TimeoutError

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot

    from pyppeteer.page import Page

import logging

logger = logging.getLogger(__name__)

LOGIN_URL = 'login.php'

EMAIL_INPUT = '#loginForm > tbody > tr.account > td:nth-child(2) > input'
PASSWORD_INPUT = '#loginForm > tbody > tr.pass > td:nth-child(2) > input'
LOGIN_BUTTON = '#loginForm > tbody > tr.loginButtonRow > td:nth-child(2) > button[type=submit]'
LOGIN_ERROR = '#error'


class TravianBotLogin(TravianBotFunction):

    def __init__(self, bot: 'TravianBot', login_page: Optional['Page']):
        super().__init__(bot)

        self.page = login_page

    @staticmethod
    async def is_login_page(server_url: str, page: 'Page') -> bool:
        if page.url == server_url or page.url.endswith(LOGIN_URL):
            return (await page.querySelector('body.login')) is not None
        return False

    async def run(self):
        if not self.page:
            self.page = await self.go_to_server_url(logger, LOGIN_URL, check_login=False)

        is_login = await TravianBotLogin.is_login_page(self.bot.server_url, self.page)

        if not is_login:
            logger.info('Already logged in')
            return

        if not self.browser:
            raise ConnectionError('Cannot login because browser is not connected')

        email, password = get_credentials()

        await self.browser.type(logger, self.page, 'Email', EMAIL_INPUT, email, 'email')

        await self.browser.type(logger, self.page, 'Password', PASSWORD_INPUT, password, 'password')

        try:
            await self.browser.click_go(logger, self.page, 'Login Button', LOGIN_BUTTON, timeout=10000)

            logger.info('Logged in')
        except TimeoutError as e:
            login_error_element = await self.page.querySelector(LOGIN_ERROR)

            login_error = await self.browser.text_content(self.page, login_error_element) if login_error_element else None

            if login_error:
                raise AuthenticationError(login_error)
            else:
                raise e


def get_credentials() -> tuple[str, str]:
    email = os.getenv('TRAVIAN_EMAIL')

    if not email:
        raise AuthenticationError('Missing TRAVIAN_EMAIL')

    password = os.getenv('TRAVIAN_PASSWORD')

    if not password:
        raise AuthenticationError('Missing TRAVIAN_PASSWORD')

    return email, password
