from abc import abstractmethod

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot
    from travian.browser import Browser


class TravianBotFunction:

    def __init__(self, bot: 'TravianBot'):
        self.bot = bot

    @property
    def browser(self) -> Optional['Browser']:
        return self.bot.browser

    @property
    def go_to_server_url(self):
        return self.bot.go_to_server_url

    @abstractmethod
    async def run(self):
        ...

    def __repr__(self):
        return self.__class__.__name__
