from abc import abstractmethod

from typing import Callable, Optional, TYPE_CHECKING

from travian.data import Data

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
    def browser_is_connected(self) -> bool:
        return self.bot.browser_is_connected

    @property
    def go_to_server_url(self):
        return self.bot.go_to_server_url

    @property
    def get_current_page_or_go_to_server_url(self):
        return self.bot.get_current_page_or_go_to_server_url

    @property
    def new_tab(self) -> bool:
        return len(self.bot.scheduler.active_tasks) > 1

    @abstractmethod
    async def run(self):
        ...

    async def schedule(self):
        await self.bot.scheduler.append(self)

    def update_data(self, update: Callable[[Data], None]):
        update(self.bot.data)
        self.bot._event_loop.run_in_executor(None, self.bot.data.save)

    def __repr__(self):
        return self.__class__.__name__
