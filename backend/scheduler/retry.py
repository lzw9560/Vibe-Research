"""S184 调研 w8e2forp7：tenacity retry 装饰器——给 flaky executor（em_get/baostock/hithink callers）
加 retry/backoff。tenacity==8.5.0 已在 requirements 但未用。~5 行/函数，零新依赖，零迁移。

用法：
    from scheduler.retry import network_retry

    @network_retry
    def fetch_daily_bars(...): ...
"""
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 网络瞬态失败 retry：3 次 + 指数 backoff（2-60s）+ 只 retry 网络异常（Timeout/Connection/OSError）
network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, max=60),
    retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
    reraise=True,
)

__all__ = ["network_retry"]
