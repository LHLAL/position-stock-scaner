"""腾讯财经数据源"""
import requests
from datetime import datetime
from typing import Optional, Dict, List

from .base import DataSource, Quote


class TencentSource(DataSource):
    name: str = "tencent"
    priority: int = 1

    def __init__(self) -> None:
        self.timeout: float = 5
        self.base_url: str = "https://qt.gtimg.cn/q"

    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        """获取单个股票报价"""
        prefix = "sh" if market.upper() == "SH" else "sz"
        url = f"{self.base_url}={prefix}{code}"

        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.text.strip()

            if not text or text == "null":
                print(f"腾讯报价为空 {market}{code}")
                return None

            # 解析: v_sh603000="1~人民网~603000~19.36~19.02~..."
            # 格式: v_{market}{code}="fields..."
            # 去除 v_sh603000=" 前缀和结尾的 "
            inner = text.split('="')[1].rstrip('";')

            if not inner:
                return None

            fields = inner.split('~')
            if len(fields) < 33:
                print(f"腾讯报价字段不足 {market}{code}: {fields}")
                return None

            # 字段索引: 1=名称, 3=当前价, 4=昨收, 32=涨跌幅%, 6=成交量
            name = fields[1] if fields[1] else ""
            price = float(fields[3]) if fields[3] else 0.0
            yesterday_close = float(fields[4]) if fields[4] else 0.0
            change_pct = float(fields[32]) if fields[32] else 0.0
            volume = int(fields[6]) if fields[6] else 0

            # 计算涨跌额
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return Quote(
                code=code,
                name=name,
                price=price,
                change_pct=change_pct,
                volume=volume,
                market=market.upper(),
                timestamp=timestamp
            )

        except requests.Timeout:
            print(f"腾讯报价超时 {market}{code}")
            return None
        except requests.RequestException as e:
            print(f"腾讯报价请求失败 {market}{code}: {e}")
            return None
        except (ValueError, IndexError) as e:
            print(f"腾讯报价解析失败 {market}{code}: {e}")
            return None
        except Exception as e:
            print(f"腾讯报价异常 {market}{code}: {e}")
            return None

    def get_quote_extended(self, code: str, market: str = "SH") -> Optional[Dict]:
        """获取扩展行情（含 PE/PB/换手率）—— 走腾讯 qt.gtimg.cn

        Returns: {'price', 'change_pct', 'volume', 'pe', 'pb', 'turnover_pct', ...}
        """
        prefix = "sh" if market.upper() == "SH" else "sz"
        try:
            import requests
            resp = requests.get(f"https://qt.gtimg.cn/q={prefix}{code}", timeout=4)
            if not resp.text or '="' not in resp.text:
                return None
            fields = resp.text.split('="', 1)[1].rstrip('";').split('~')
            def f(i):
                try:
                    return float(fields[i]) if len(fields) > i and fields[i] else None
                except (ValueError, IndexError):
                    return None
            return {
                'code': code,
                'name': fields[1] if len(fields) > 1 else '',
                'price': f(3),
                'change_pct': f(32),
                'volume': f(6),
                'pe': f(39),
                'pb': f(46),
                'turnover_pct': f(38),
                'market_cap_yi': f(45),
            }
        except Exception as e:
            print(f"腾讯扩展行情失败 {code}: {e}")
            return None

    def get_quote_with_prefix(self, code_with_prefix: str) -> Optional[Dict]:
        """用 'sh600519' / 'sz000001' / 'bj830xxx' 形式拉行情"""
        try:
            import requests
            resp = requests.get(f"https://qt.gtimg.cn/q={code_with_prefix}", timeout=8)
            if not resp.text or '="' not in resp.text:
                return None
            fields = resp.text.split('="', 1)[1].rstrip('";').split('~')
            if len(fields) < 33:
                return None
            def f(i, default=0):
                try:
                    return float(fields[i]) if fields[i] else default
                except (ValueError, IndexError):
                    return default
            return {
                'code': fields[2],
                'name': fields[1],
                'price': f(3),
                'change_pct': f(32),
                'volume': int(f(6, 0)),
            }
        except Exception as e:
            print(f"腾讯带前缀行情失败 {code_with_prefix}: {e}")
            return None

    def fetch_batch_with_prefix(self, codes_with_prefix: List[str], delay: float = 0.2) -> Dict[str, Dict]:
        """批量拉多只带前缀的行情（一次性 HTTP）—— 返回 {raw_code: {name,price,change_pct,volume}}"""
        if not codes_with_prefix:
            return {}
        result: Dict[str, Dict] = {}
        try:
            import requests
            url = f"https://qt.gtimg.cn/q={','.join(codes_with_prefix)}"
            resp = requests.get(url, timeout=8)
            if not resp.text:
                return result
            for line in resp.text.strip().split(';'):
                if '="1~' not in line:
                    continue
                try:
                    inner = line.split('="')[1].rstrip('";')
                    fields = inner.split('~')
                    if len(fields) < 33:
                        continue
                    raw_code = fields[2]
                    name = fields[1]
                    price = float(fields[3]) if fields[3] and fields[3] != '-' else 0
                    change_pct = float(fields[32]) if fields[32] else 0
                    volume = int(float(fields[6])) if fields[6] else 0
                    result[raw_code] = {
                        'name': name, 'price': price,
                        'change_pct': change_pct, 'volume': volume,
                    }
                except Exception:
                    continue
        except Exception as e:
            print(f"腾讯批量拉取失败: {e}")
        return result

    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Quote]:
        """批量获取股票报价"""
        if not codes:
            return {}

        prefix = "sh" if market.upper() == "SH" else "sz"

        # 拼接多个代码: q=sh603000,q=sz000001
        code_str = ",".join([f"{prefix}{c}" for c in codes])
        url = f"{self.base_url}={code_str}"

        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.text.strip()

            if not text:
                return {}

            results = {}
            # 按行分割，每行一个股票
            lines = text.split(';')

            for line in lines:
                line = line.strip()
                if not line or line == "null":
                    continue

                try:
                    # 解析: v_sh603000="1~人民网~603000~..."
                    inner = line.split('="')[1].rstrip('";')
                    fields = inner.split('~')

                    if len(fields) < 33:
                        continue

                    code = fields[2]  # 字段2是股票代码
                    name = fields[1]
                    price = float(fields[3]) if fields[3] else 0.0
                    change_pct = float(fields[32]) if fields[32] else 0.0
                    volume = int(fields[6]) if fields[6] else 0

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    results[code] = Quote(
                        code=code,
                        name=name,
                        price=price,
                        change_pct=change_pct,
                        volume=volume,
                        market=market.upper(),
                        timestamp=timestamp
                    )

                except (ValueError, IndexError) as e:
                    # 跳过解析失败的行
                    continue

            return results

        except requests.Timeout:
            print(f"腾讯批量报价超时 {market}{codes}")
            return {}
        except requests.RequestException as e:
            print(f"腾讯批量报价请求失败 {market}{codes}: {e}")
            return {}
        except Exception as e:
            print(f"腾讯批量报价异常 {market}{codes}: {e}")
            return {}

    def health_check(self) -> bool:
        """健康检查"""
        try:
            test_quote = self.get_quote("603000", "SH")
            return test_quote is not None
        except Exception:
            return False