from datetime import datetime, timedelta

from travian.bot_functions import TravianBotFunction

from travian.data import Data

import logging

logger = logging.getLogger(__name__)


class TravianBotFarmingList(TravianBotFunction):

    FARMING_LIST_URL = 'build.php?id=39&gid=16&tt=99'

    async def run(self):
        page = await self.go_to_server_url(logger, TravianBotFarmingList.FARMING_LIST_URL, new_tab=self.new_tab)

        if not self.browser:
            raise ConnectionError('Cannot farm list because browser is not connected')

        raid_all_button = '#raidList > div.startAllWrapper > div.startAllButtons > button.startAll'
        await self.browser.click(logger, page, 'Raid All', raid_all_button)

        self.update_data(self.__set_last_farming)

        await self.browser.close_page(logger, page, delay_seconds=5)

    def __set_last_farming(self, data: Data):
        data.farming_list.last_farming = datetime.now()

    @property
    def next_farming_datetime(self) -> datetime:
        return self.bot.data.farming_list.last_farming + timedelta(minutes=self.bot.config.farming_list.interval_minutes)

    @property
    def can_farm(self) -> bool:
        return datetime.now() >= self.next_farming_datetime

    async def schedule(self):
        interval_seconds = self.bot.config.farming_list.interval_minutes * 60

        if self.can_farm:
            await self.bot.scheduler.append(self, interval_seconds=interval_seconds, reschedule_on_error=True)
        else:
            await self.bot.scheduler.schedule(self, self.next_farming_datetime,
                                              interval_seconds=interval_seconds, reschedule_on_error=True)
