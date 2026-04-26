"""屯象OS test infrastructure（Sprint F2）.

通用故障注入工具集。当前内含 ToxiproxyClient — 通过 toxiproxy admin API
对预置 TCP 代理注入 latency / packet loss / disable 等 toxics。

警告：本目录下任何工具不得在 Tier 1 测试套件中使用，等 §19 独立验证通过后再接入。
"""

from shared.test_infra.toxiproxy_client import ToxiproxyClient, ToxiproxyError

__all__ = ["ToxiproxyClient", "ToxiproxyError"]
