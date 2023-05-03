from travian.config import DataSection, LoadableConfiguration

from datetime import datetime

from settings import format_date

import logging

logger = logging.getLogger(__name__)

DATA_FILE = '.data.yml'


class FarmingListData(DataSection):

    last_farming: datetime = datetime.fromtimestamp(0)

    def set_last_farming(self, value: datetime):
        self.last_farming = value
        logger.info(f"Set last farming: {format_date(self.last_farming)}")


class Data(LoadableConfiguration):

    farming_list: FarmingListData

    def __init__(self, path: str = DATA_FILE):
        super().__init__(path)

    def load(self):
        try:
            super().load()
        except FileNotFoundError:
            self._loaded = True
        self.farming_list = FarmingListData(self, 'farming-list')


def load_data() -> Data:
    data = Data()
    data.load()
    return data
