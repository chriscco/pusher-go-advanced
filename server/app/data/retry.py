import time


def with_retry(fn, *, attempts=3, base_delay=0.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 数据源各异，统一兜底重试
            last = e
            if base_delay and i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last
