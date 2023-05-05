import re
import json

from datetime import timedelta

from travian.bot_functions import TravianBotFunction

from pyppeteer.page import PageError

from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    from pyppeteer.page import Page, ElementHandle

import logging

logger = logging.getLogger(__name__)

ADVENTURES_URL = 'hero/adventures'

NOT_ADVENTURE = '#topBarHero > a.adventure > svg.adventure'
AVAILABLE_ADVENTURES = '#topBarHero > a.adventure > div.content'
HERO_AT_HOME = '#topBarHero > div.heroStatus > a > i.heroHome'
HERO_RUNNING = '#topBarHero > div.heroStatus > a > i.heroRunning'

HEALTH_BAR = '#topBarHero > svg.health > path'
HEALTH_BAR_HOVER = 'aria-describedby'
HEALTH_BAR_TIPPY = 'div.tippy-box > div.tippy-content > div.text'
HEALTH_STATUS_REGEX = re.compile(r'\d+')

ADVENTURES = '#heroAdventure > table > tbody > tr'
ADVENTURE_DIFFICULTY = 'td.difficulty > i'
ADVENTURE_COORDINATES = 'td.coordinates > a'
ADVENTURE_DURATION = 'td.duration'
AVENTURE_DURATION_REGEX = re.compile(r'(\d+):(\d+):(\d+)')
ADVENTURE_START_BUTTON = 'td.button > button'

ADVENTURE_HERO_STATUS = '#heroAdventure > div.heroState > div > span'
ADVENTURE_HERO_STATUS_AFTER = '#heroAdventure > div > div > div > span:nth-child(1)'
ADVENTURE_HERO_STATUS_AFTER_ARRIVAL = '#heroAdventure > div > div > div > span:nth-child(2) > span'
ADVENTURE_CONTINUE_AFTER_BUTTON = '#heroAdventure > div > button'


class TravianHeroAdventures(TravianBotFunction):

    async def run(self):
        page = await self.get_current_page_or_go_to_server_url(logger, ADVENTURES_URL, new_tab=self.new_tab)

        if not self.browser:
            raise ConnectionError('Cannot do adventures because browser is not connected')

        not_adventure = await page.querySelector(NOT_ADVENTURE)

        if not_adventure:
            logger.info('No adventure available')
        else:
            available_adventures = await page.querySelector(AVAILABLE_ADVENTURES)

            if available_adventures:
                available_adventures = await self.browser.text_content(page, available_adventures)

            if available_adventures:
                hero_available = await page.querySelector(HERO_AT_HOME)

                if hero_available:
                    if await self.__check_health(page):
                        if page.url != self.bot.get_server_url(ADVENTURES_URL):
                            page = await self.go_to_server_url(logger, ADVENTURES_URL, new_tab=self.new_tab)

                        adventure = await self.__select_adventure(page)
                        adventure_info = await self.__get_adventure_info(page, adventure)

                        hero_status_before = await self.browser.text_content(page, ADVENTURE_HERO_STATUS)

                        if hero_status_before:
                            logger.info(hero_status_before)

                        start_adventure_button = await adventure.querySelector(ADVENTURE_START_BUTTON)

                        if start_adventure_button:
                            await self.browser.click_element(logger, page, start_adventure_button, f'Start {adventure_info}')

                            await self.browser.wait(logger, page, milliseconds=3000)

                            hero_status_after = await self.browser.text_content(page, ADVENTURE_HERO_STATUS_AFTER)
                            hero_status_arrival = await self.browser.text_content(page, ADVENTURE_HERO_STATUS_AFTER_ARRIVAL)

                            if hero_status_after and hero_status_arrival:
                                logger.info(f'{TravianHeroAdventures.__clean(hero_status_after)} {hero_status_arrival}')

                            continue_button = await page.querySelector(ADVENTURE_CONTINUE_AFTER_BUTTON)

                            if continue_button:
                                await self.browser.click_element(logger, page, continue_button, 'Continue')
                        else:
                            raise PageError('Cannot start adventure')
                else:
                    hero_status = 'not at home' if (await page.querySelector(HERO_RUNNING)) else 'dead'
                    logger.info(f'There are {available_adventures} adventures available, but hero is {hero_status}.')

        await self.browser.close_page(None, page, delay_seconds=2)

    async def schedule(self):
        await self.bot.scheduler.append(self, interval_seconds=self.bot.config.adventures.interval_seconds)

    async def __check_health(self, page: 'Page'):
        health_bar = await page.querySelector(HEALTH_BAR)

        if health_bar and self.browser:
            await self.__hover_health_bar(page, health_bar)

            tippy_id = await self.browser.attribute(page, f'{HEALTH_BAR}[{HEALTH_BAR_HOVER}]', HEALTH_BAR_HOVER)

            if tippy_id:
                tippy_id = tippy_id.split(' ')[0]

                health_status = await self.browser.text_content(page, f"#{tippy_id} > {HEALTH_BAR_TIPPY}")

                if health_status:
                    health_amount = HEALTH_STATUS_REGEX.search(health_status)

                    if health_amount:
                        health_amount = int(health_amount.group(0))

                        if health_amount >= self.bot.config.adventures.min_health:
                            logger.debug(f"Hero health is {health_amount}%")
                            return True
                        else:
                            logger.info(f"Hero health is {health_amount}% so it's too risky to do an adventure.")
            else:
                raise PageError(f'Cannot get health tippy id')

        return False

    async def __hover_health_bar(self, page: 'Page', health_bar: 'ElementHandle'):
        # health_bar.hover() but with custom position (middle does not show the health tippy box)
        if self.browser:
            await health_bar.focus()
            await health_bar._scrollIntoViewIfNeeded()
            health_bar_box = await self.browser.bounding_box(page, health_bar)
            x = health_bar_box['left'] + health_bar_box['width'] / 6
            y = health_bar_box['top'] + int(health_bar_box['height'])
            await health_bar._page.mouse.move(x, y)

    async def __select_adventure(self, page: 'Page') -> 'ElementHandle':
        async def get_adventure_with_duration(adventure: 'ElementHandle') -> tuple['ElementHandle', timedelta]:
            if self.browser:
                adventure_duration = await adventure.querySelector(ADVENTURE_DURATION)  # ElementHandle

                if adventure_duration:
                    adventure_duration = await self.browser.text_content(page, adventure_duration)  # str

                    if adventure_duration:
                        adventure_duration = AVENTURE_DURATION_REGEX.match(adventure_duration)  # Match

                        if adventure_duration:
                            hours, minutes, seconds = adventure_duration.groups()
                            adventure_duration = timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds))
            else:
                adventure_duration = None

            if adventure_duration is None:
                raise PageError('Cannot get adventure duration')

            return (adventure, cast(timedelta, adventure_duration))

        await page.waitForSelector(ADVENTURES)

        adventures = await page.querySelectorAll(ADVENTURES)

        if not adventures or not self.browser:
            raise PageError('Cannot get available adventures')

        adventures = [await get_adventure_with_duration(adventure) for adventure in adventures]

        adventures.sort(key=lambda adventure_duration: adventure_duration[1])

        return adventures[0][0]

    async def __get_adventure_info(self, page: 'Page', adventure: 'ElementHandle') -> str:
        adventure_difficulty = await adventure.querySelector(ADVENTURE_DIFFICULTY)

        if adventure_difficulty and self.browser:
            adventure_difficulty = await self.browser.attribute(page, adventure_difficulty, 'alt')

        if adventure_difficulty is None:
            raise PageError('Cannot get adventure difficulty')

        adventure_coordinates = await adventure.querySelector(ADVENTURE_COORDINATES)

        if adventure_coordinates and self.browser:
            adventure_coordinates = await self.browser.attribute(page, adventure_coordinates, 'data-load-tooltip-data')
        else:
            adventure_coordinates = None

        if adventure_coordinates is None:
            raise PageError('Cannot get adventure coordinates')

        adventure_coordinates = json.loads(adventure_coordinates)

        return f"adventure ({adventure_difficulty}) at ({adventure_coordinates['x']}|{adventure_coordinates['y']})"

    @staticmethod
    def __clean(s: str) -> str:
        return s.replace('‭', '').replace('‬', '')
