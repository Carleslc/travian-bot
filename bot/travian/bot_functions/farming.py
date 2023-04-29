from datetime import datetime, timedelta

from travian.bot_functions import TravianBotFunction

from travian.data import Data

from pyppeteer.page import Page, PageError

import logging

logger = logging.getLogger(__name__)

FARMING_LIST_URL = 'build.php?id=39&gid=16&tt=99'

RAID_ALL_LISTS_BUTTON = '#raidList > div.startAllWrapper > div.startAllButtons > button.startAll'

FARMING_LISTS = '#raidList div.raidList > div.raidListContent > form'
FARMING_TOGGLE_CHECKED_BUTTON = 'div.buttonWrapper > button.stateToggleButton'
FARMING_TARGETS = 'table > tbody > tr.slotRow.slotActive'
GREEN_ATTACK_ICON = 'td.lastRaid > div > img.iReport.iReport1'
TARGET_VILLAGE = 'td.target > a'
TARGET_CHECKBOX = 'td.checkbox > input.markSlot'


class TravianBotFarmingList(TravianBotFunction):

    async def run(self):
        page = await self.go_to_server_url(logger, FARMING_LIST_URL, new_tab=self.new_tab)

        if not self.browser:
            raise ConnectionError('Cannot farm list because browser is not connected')

        await self.__check_farming_lists(page)

        await self.browser.click(logger, page, 'Raid All', RAID_ALL_LISTS_BUTTON)

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

    async def __check_farming_lists(self, page: 'Page'):
        logger.debug('Checking farming lists')

        if self.browser:
            await page.waitForSelector(FARMING_LISTS)

            for farming_list in (await page.querySelectorAll(FARMING_LISTS)):
                disable_targets = 0

                for farming_target in (await farming_list.querySelectorAll(FARMING_TARGETS)):
                    is_green_attack = await farming_target.querySelector(GREEN_ATTACK_ICON)

                    if not is_green_attack:
                        target_checkbox = await farming_target.querySelector(TARGET_CHECKBOX)

                        target_village = await farming_target.querySelector(TARGET_VILLAGE)

                        if target_village:
                            target_village_name = await self.browser.text_content(page, target_village)
                            target_village_position_url = await self.browser.attribute(page, target_village, 'href')
                            target_village_str = str(target_village_name)
                            if target_village_position_url:
                                target_village_str += f' ({self.bot.get_server_url(target_village_position_url)})'
                        else:
                            target_village_str = None

                        if target_checkbox:
                            target_village_str = f'Mark as inactive: {target_village_str}'
                            await self.browser.click_element(logger, target_checkbox, target_village_str)
                            disable_targets += 1

                if disable_targets:
                    await self.browser.wait(logger, page, 1000)

                    disable_all_checked_button = await farming_list.querySelector(FARMING_TOGGLE_CHECKED_BUTTON)

                    if disable_all_checked_button:
                        await self.browser.click_element(logger, disable_all_checked_button, f'Disable {disable_targets} farming targets (not green attack)')
                    else:
                        raise PageError(f'Cannot disable {disable_targets} farming targets (not green attack)')
