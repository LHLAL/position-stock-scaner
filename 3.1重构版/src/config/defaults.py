DEFAULT_CONFIG = {
    "api_keys": {
        "openai": "",
        "anthropic": "",
        "zhipu": "",
        "deepseek": ""
    },
    "ai": {
        "model_preference": "openai",
        "models": {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "zhipu": "glm-4-flash",
            "deepseek": "deepseek-chat"
        },
        "temperature": 0.7,
        "max_tokens": 4000
    },
    "analysis_weights": {
        "technical": 0.4,
        "fundamental": 0.4,
        "sentiment": 0.2
    },
    "analysis_params": {
        "max_news_count": 100,
        "technical_period_days": 365,
        "financial_indicators_count": 25
    },
    "cache": {
        "enabled": False,
        "price_hours": 1,
        "fundamental_hours": 6,
        "news_hours": 2
    },
    "web_auth": {
        "enabled": False,
        "password": "",
        "session_timeout": 3600
    },
    "data_sources": {
        "tencent": {"enabled": True, "priority": 1, "timeout": 5},
        "yahoo": {"enabled": True, "priority": 2, "timeout": 10},
        "akshare": {"enabled": True, "priority": 3, "timeout": 30}
    },
    "server": {
        "host": "0.0.0.0",
        "port": 5000,
        "debug": False,
        "threaded": True,
        "max_workers": 4
    }
}