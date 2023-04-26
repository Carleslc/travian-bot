import yaml


def load_config_file(path='config.yml'):
    with open(path, 'r') as file:
        return yaml.safe_load(file)
