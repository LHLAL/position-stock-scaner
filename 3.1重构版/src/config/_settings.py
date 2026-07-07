import json
from pathlib import Path
from .defaults import DEFAULT_CONFIG

class Settings:
    _instance = None

    def __init__(self):
        self._config = None
        self._config_path = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self, config_path=None):
        if config_path is None:
            # v1.3: 配置文件统一在项目根，不再回退到 3.0 webapp 目录
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config.json"

        self._config_path = Path(config_path)

        if self._config_path.exists():
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self._config = self._deep_merge(DEFAULT_CONFIG, loaded)
            except Exception as e:
                print(f"配置加载失败: {e}, 使用默认配置")
                self._config = DEFAULT_CONFIG.copy()
        else:
            print(f"配置文件不存在: {self._config_path}, 使用默认配置")
            self._config = DEFAULT_CONFIG.copy()

        return self

    def _deep_merge(self, default, loaded):
        result = default.copy()
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key_path, default=None):
        if self._config is None:
            self.load()

        keys = key_path.split('.')
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def get_all(self):
        if self._config is None:
            self.load()
        return self._config

settings = Settings.get_instance()