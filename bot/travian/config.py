import yaml

from typing import Union, Any

import logging

logger = logging.getLogger(__name__)

CONFIG_FILE = 'config.yml'


class ConfigurationSection:

    def __init__(self, section: Union[dict[str, Any], 'ConfigurationSection'] = {}):
        self._self_variables(__section__=dict())
        self.update(section)

    def __getitem__(self, key: str) -> Any:
        return self.__section__[ConfigurationSection.__key(key)]

    def __getattr__(self, key: str) -> Any:
        return self.__getitem__(key)

    def __contains__(self, key: str) -> bool:
        return ConfigurationSection.__key(key) in self.__section__

    def __setitem__(self, key: str, value: Any):
        ConfigurationSection.__build_section(self, {key: value})

    def __setattr__(self, key: str, value: Any):
        self[key] = value

    def get(self, key: str, default=None) -> Any:
        return self.__section__.get(ConfigurationSection.__key(key), default)

    def update(self, items: Union[dict[str, Any], 'ConfigurationSection']):
        items = items.__section__ if isinstance(items, ConfigurationSection) else items
        ConfigurationSection.__build_section(self, items)

    def clear(self):
        self.__section__.clear()

    def replace(self, section: dict[str, Any]):
        self.clear()
        self.update(section)

    def as_dict(self, exclude_keys: set[str] = set()) -> dict[str, Any]:
        return ConfigurationSection.__build_dict(self, exclude_keys)

    def _self_variables(self, **kwargs):
        """__setattr__ only for self.__dict__ instead of self.__section__"""
        for var, value in kwargs.items():
            self.__dict__[var] = value

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
            key = ConfigurationSection.__key(key)
            if key not in section.__dict__ or not key.startswith('_'):
                section.__section__[key] = value
            section.__dict__[key] = value

    @staticmethod
    def __build_dict(section: 'ConfigurationSection', exclude_keys: set[str] = set()) -> dict[str, Any]:
        def fill_dict(d: dict, section: ConfigurationSection):
            for key, value in section.__section__.items():
                if key not in exclude_keys:
                    if isinstance(value, ConfigurationSection):
                        value = fill_dict(dict(), value)
                    d[ConfigurationSection.__reverse_key(key)] = value
            return d

        return fill_dict(dict(), section)

    def __str__(self) -> str:
        return str(self.as_dict())

    def __repr__(self) -> str:
        self_vars = {key: value for key, value in self.__dict__.items() if key not in self}
        return str(self_vars | self.as_dict())


class LoadableConfiguration(ConfigurationSection):

    path: str

    def __init__(self, path: str):
        super().__init__()
        self._self_variables(path=path, _loaded=False)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self):
        self.replace(load_yml_file(self.path))
        self._loaded = True
        logger.debug(f'loaded {self.path}: {self}')

    def save(self):
        if self.is_loaded:
            save_yml_file(self.as_dict(), self.path)
        else:
            logger.warning(f'Cannot save {self.path}: File not loaded')


class DataSection(ConfigurationSection):

    def __init__(self, parent: ConfigurationSection, key: str):
        super().__init__(parent.get(key, {}))


class ConfigFunction(DataSection):

    enabled = False

    @property
    def is_enabled(self) -> bool:
        return self.enabled


class PeriodicFunction(ConfigFunction):

    interval_minutes: int = 30

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60


class FarmingList(PeriodicFunction):
    ...


class Config(LoadableConfiguration):

    farming_list: FarmingList

    def __init__(self, path: str = CONFIG_FILE):
        super().__init__(path)

    def load(self):
        super().load()
        self.farming_list = FarmingList(self, 'farming-list')


def load_config() -> Config:
    config = Config()
    config.load()
    return config


def load_yml_file(path: str) -> dict[str, Any]:
    with open(path, 'r') as file:
        return yaml.safe_load(file)


def save_yml_file(data: dict[str, Any], path: str):
    with open(path, 'w') as file:
        yaml.dump(data, file)
