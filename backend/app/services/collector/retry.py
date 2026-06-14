import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# 东财限流：指数退避 1s→2s→4s，最多 4 次
em_retry = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(
        (httpx.TransportError, httpx.RemoteProtocolError, httpx.TimeoutException)
    ),
)
