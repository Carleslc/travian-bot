from travian.config import DataSection, ConfigurationSection, load_yml_file, save_yml_file

from datetime import datetime

DATA_FILE = '.data.yml'


class FarmingListData(DataSection):

    last_farming: datetime = datetime.fromtimestamp(0)


class Data(ConfigurationSection):

    farming_list: FarmingListData

    def load(self, path=DATA_FILE):
        try:
            self.replace(load_yml_file(path))
        except FileNotFoundError:
            pass
        self.farming_list = FarmingListData(self, 'farming-list')

    def save(self, path=DATA_FILE):
        save_yml_file(self.as_dict(), path)


def load_data() -> Data:
    data = Data()
    data.load()
    return data
