import yaml

from typing import Union, Any

CONFIG_FILE = 'config.yml'


class ConfigurationSection:

    def __init__(self, section: Union[dict[str, Any], 'ConfigurationSection'] = {}):
        self.update(section)

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[ConfigurationSection.__key(key)]

    def __contains__(self, key: str) -> bool:
        return ConfigurationSection.__key(key) in self.__dict__

    def __setitem__(self, key: str, value: Any):
        self.__setattr__(key, value)

    def __setattr__(self, key: str, value: Any):
        ConfigurationSection.__build_section(self, {key: value})

    def get(self, key: str, default=None) -> Any:
        return self.__dict__.get(ConfigurationSection.__key(key), default)

    def update(self, items: Union[dict[str, Any], 'ConfigurationSection']):
        items = items.__dict__ if isinstance(items, ConfigurationSection) else items
        ConfigurationSection.__build_section(self, items)

    def clear(self):
        self.__dict__.clear()

    def replace(self, section: dict[str, Any]):
        self.clear()
        self.update(section)

    def as_dict(self, exclude_keys: set[str] = set()) -> dict[str, Any]:
        return ConfigurationSection.__build_dict(self, exclude_keys)

    @staticmethod
    def __key(key: str) -> str:
        return key.replace('-', '_')

    @staticmethod
    def __reverse_key(key: str) -> str:
        return key.replace('_', '-')

    @staticmethod
    def __build_section(section: 'ConfigurationSection', items: dict[str, Any]):
        for key, value in items.items():
            if isinstance(value, dict):
                child_section = ConfigurationSection()
                ConfigurationSection.__build_section(child_section, value)
                value = child_section
            section.__dict__[ConfigurationSection.__key(key)] = value

    @staticmethod
    def __build_dict(section: 'ConfigurationSection', exclude_keys: set[str] = set()) -> dict[str, Any]:
        def fill_dict(d: dict, section: ConfigurationSection):
            for key, value in section.__dict__.items():
                if key not in exclude_keys:
                    if isinstance(value, ConfigurationSection):
                        value = fill_dict(dict(), value)
                    d[ConfigurationSection.__reverse_key(key)] = value
            return d

        return fill_dict(dict(), section)


class DataSection(ConfigurationSection):

    def __init__(self, parent: ConfigurationSection, key: str):
        super().__init__(parent.get(key, {}))


class ConfigFunction(DataSection):

    enabled = False

    @property
    def is_enabled(self) -> bool:
        return self.enabled


class FarmingList(ConfigFunction):

    interval_minutes: int = 30


class Config(ConfigurationSection):

    farming_list: FarmingList

    def load(self, path=CONFIG_FILE):
        config = load_yml_file(path)
        self.replace(config)
        self.farming_list = FarmingList(self, 'farming-list')

    def save(self, path=CONFIG_FILE):
        save_yml_file(self.as_dict(), path)


def load_config() -> Config:
    config = Config()
    config.load()
    return config


def load_yml_file(path=CONFIG_FILE) -> dict[str, Any]:
    with open(path, 'r') as file:
        return yaml.safe_load(file)


def save_yml_file(data: dict[str, Any], path=CONFIG_FILE):
    with open(path, 'w') as file:
        yaml.dump(data, file)
