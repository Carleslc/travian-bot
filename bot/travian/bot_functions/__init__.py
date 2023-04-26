from abc import abstractmethod

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot
    from travian.browser import Browser


class TravianBotFunction:

    def __init__(self, bot: 'TravianBot'):
        self.bot = bot

    @property
    def browser(self) -> 'Browser':
        return self.bot.browser

    @property
    def go_to_server_url(self):
        return self.bot.go_to_server_url

    @abstractmethod
    async def run(self):
        ...
