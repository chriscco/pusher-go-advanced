from datetime import datetime, timezone, timedelta

_BEIJING = timezone(timedelta(hours=8))


def today_key() -> str:
    return datetime.now(_BEIJING).strftime("%Y-%m-%d")


class DailyCache:
    def __init__(self):
        self._store = {}

    def _k(self, key):
        # 引用模块级 today_key，便于测试 monkeypatch
        from app.data import cache as _self
        return f"{_self.today_key()}:{key}"

    def get(self, key):
        return self._store.get(self._k(key))

    def set(self, key, value):
        self._store[self._k(key)] = value
