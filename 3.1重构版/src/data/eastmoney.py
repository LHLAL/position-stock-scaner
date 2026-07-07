"""东方财富数据源"""
import requests
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .base import DataSource, Quote

class EastMoneySource(DataSource):
    name = "eastmoney"
    priority = 1

    def __init__(self):
        self.timeout = 15

    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        return None  # 东方财富主要用于研报和资金流

    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Optional[Quote]]:
        return {code: None for code in codes}

    def get_research_reports(self, code: str, max_pages: int = 3) -> List[Dict]:
        """获取研报"""
        url = "https://reportapi.eastmoney.com/report/list"
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/"
        })
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*", "pageSize": "100", "industry": "*",
                "rating": "*", "ratingChange": "*",
                "beginTime": "2000-01-01", "endTime": "2030-01-01",
                "pageNo": str(page), "fields": "", "qType": "0",
                "orgCode": "", "code": code, "rcode": "",
                "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            }
            try:
                resp = session.get(url, params=params, timeout=self.timeout)
                data = resp.json()
                rows = data.get("data") or []
                if not rows:
                    break
                all_records.extend(rows)
                if page >= (data.get("TotalPage", 1) or 1):
                    break
                import time
                time.sleep(0.3)
            except Exception as e:
                print(f"研报第{page}页失败: {e}")
                break
        reports = []
        for r in all_records[:30]:
            reports.append({
                "title": r.get("title", ""),
                "date": (r.get("publishDate") or "")[:10],
                "org": r.get("orgSName", ""),
                "rating": r.get("emRatingName", ""),
                "predict_eps_this_year": r.get("predictThisYearEps"),
                "predict_eps_next_year": r.get("predictNextYearEps"),
                "industry": r.get("indvInduName", ""),
            })
        return reports

    def get_daily_dragon_tiger(self, code: str = None, date: str = None, look_back: int = 30) -> Dict:
        """获取龙虎榜数据（个股维度）"""
        import akshare as ak
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            start = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=look_back)
            start_str = start.strftime("%Y%m%d")
            end_str = date.replace("-", "")
            records = []
            try:
                df = ak.stock_lhb_detail_em(start_date=start_str, end_date=end_str)
                if not df.empty:
                    df_stock = df[df["代码"] == code] if code else df
                    for _, row in df_stock.iterrows():
                        records.append({
                            "date": str(row.get("日期", "")),
                            "reason": row.get("解读", ""),
                            "net_buy": row.get("龙虎榜净买额", 0),
                            "turnover": row.get("换手率", 0),
                        })
            except Exception:
                pass
            seats = {"buy": [], "sell": []}
            if records:
                latest_date = records[0]["date"].replace("-", "")[:8]
                try:
                    df_detail = ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="买入")
                    if not df_detail.empty:
                        for _, row in df_detail.head(5).iterrows():
                            seats["buy"].append({
                                "name": row.get("营业部名称", ""),
                                "buy_amt": row.get("买入额", 0),
                                "sell_amt": row.get("卖出额", 0),
                                "net": row.get("净额", 0),
                            })
                except Exception:
                    pass
                try:
                    df_detail = ak.stock_lhb_stock_detail_em(symbol=code, date=latest_date, flag="卖出")
                    if not df_detail.empty:
                        for _, row in df_detail.head(5).iterrows():
                            seats["sell"].append({
                                "name": row.get("营业部名称", ""),
                                "buy_amt": row.get("买入额", 0),
                                "sell_amt": row.get("卖出额", 0),
                                "net": row.get("净额", 0),
                            })
                except Exception:
                    pass
            institution = {}
            try:
                df_inst = ak.stock_lhb_jgmmtj_em(symbol=code)
                if not df_inst.empty:
                    row = df_inst.iloc[0]
                    institution = {
                        "buy_count": row.get("买入机构数", 0),
                        "sell_count": row.get("卖出机构数", 0),
                        "net_amount": row.get("机构净买入额", 0),
                    }
            except Exception:
                pass
            return {"records": records, "seats": seats, "institution": institution}
        except Exception as e:
            print(f"东方财富龙虎榜失败: {e}")
            return {"records": [], "seats": {"buy": [], "sell": []}, "institution": {}}

    def get_lockup_expiry(self, stock_code: str = None, forward_days: int = 90) -> Dict:
        """获取限售股解禁数据"""
        import akshare as ak
        trade_date = datetime.now().strftime("%Y-%m-%d")
        try:
            history = []
            try:
                if stock_code:
                    df = ak.stock_restricted_release_queue_em(symbol=stock_code)
                    if not df.empty:
                        for _, row in df.head(15).iterrows():
                            history.append({
                                "date": str(row.get("解禁时间", "")),
                                "type": row.get("限售股类型", ""),
                                "shares": row.get("解禁数量", 0),
                                "ratio": row.get("实际解禁市值占总市值比例", 0),
                            })
            except Exception:
                pass
            upcoming = []
            end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
            end_str = end_date.strftime("%Y%m%d")
            today_str = trade_date.replace("-", "")
            try:
                df = ak.stock_restricted_release_detail_em(date=today_str)
                if not df.empty:
                    df_stock = df[df["股票代码"] == stock_code] if stock_code else df
                    for _, row in df_stock.iterrows():
                        upcoming.append({
                            "date": str(row.get("解禁日期", "")),
                            "type": row.get("限售股类型", ""),
                            "shares": row.get("解禁数量", 0),
                            "float_ratio": row.get("占流通股比例", 0),
                        })
            except Exception:
                pass
            return {"history": history, "upcoming": upcoming}
        except Exception as e:
            print(f"东方财富限售股解禁失败: {e}")
            return {"history": [], "upcoming": []}

    def get_northbound(self) -> Dict:
        """获取北向资金"""
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "sortColumns": "TRADE_DATE",
            "sortTypes": -1,
            "pageSize": 1,
            "pageNumber": 1,
            "reportName": "RPT_MUTUAL_MARKET_SH"
        }
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            result = data.get("result")
            if result is None:
                return {"hgt_yi": 0, "sgt_yi": 0, "total_yi": 0}
            result_data = result.get("data", []) if isinstance(result, dict) else []
            if not result_data:
                return {"hgt_yi": 0, "sgt_yi": 0, "total_yi": 0}
            first = result_data[0]
            hgt = float(first.get("HGT_MONEY", 0) or 0) / 100000000
            sgt = float(first.get("SGT_MONEY", 0) or 0) / 100000000
            return {
                "hgt_yi": hgt,
                "sgt_yi": sgt,
                "total_yi": hgt + sgt
            }
        except Exception as e:
            print(f"东方财富北向资金失败: {e}")
            return {"hgt_yi": 0, "sgt_yi": 0, "total_yi": 0}