"""铲子股知识库 —— 热门板块 → 卡脖子环节关键词

v1 设计：硬编码 14 个当前主流热点板块，每个板块列出
- 时代趋势（不可逆）
- 卡脖子环节（铲子股所在）
- 关键词（用于在股票名称/产品中识别）
- 行业名同义词（用于匹配 THS 板块名）

数据更新策略：每个季度人工 review；遇到新增大题材补一行。
"""
from __future__ import annotations
from typing import Dict, List


# ── 板块 → 卡脖子环节 ──────────────────────────
# keyword 匹配规则：在股票名称或主营业务产品中包含（避免误匹配板块名）
BOTTLENECK_KB: Dict[str, Dict] = {
    'AI算力': {
        'trend': 'AI 大模型训练算力需求不可逆增长，光模块/液冷/电源是物理瓶颈',
        'bottleneck': '光模块（800G/1.6T）、液冷板、服务器电源、HBM 配套、CCL 高频基板',
        'keywords': ['光模块', '液冷', 'CPO', 'LPO', '电源', 'CCL', '高频高速', '覆铜板', '光器件', '连接器', '光通信'],
        'industry_alias': ['通信设备', '光通信', '通信', '元器件', '电子元件'],
    },
    '半导体设备': {
        'trend': '国产替代加速，先进制程/存储扩产对设备需求确定性高',
        'bottleneck': '刻蚀机、薄膜沉积、量测检测、清洗机、离子注入、化学机械抛光（CMP）',
        'keywords': ['刻蚀', '薄膜', '沉积', '量测', '检测', '清洗机', '离子注入', 'CMP', '抛光', '光刻机', '半导体设备'],
        'industry_alias': ['半导体', '电子', '元器件'],
    },
    '半导体材料': {
        'trend': '国产化率每提升 1pct 都是百亿级市场，材料端比设备端更稀缺',
        'bottleneck': '光刻胶、电子特气、靶材、湿电子化学品、CMP 抛光液、12 寸大硅片',
        'keywords': ['光刻胶', '电子特气', '靶材', '湿电子', '抛光液', '硅片', '电子化学品', '半导体材料'],
        'industry_alias': ['半导体', '化工', '材料'],
    },
    '存储芯片': {
        'trend': 'DRAM/NAND 周期反转，HBM/AI 存储需求结构性紧缺',
        'bottleneck': 'HBM 封装、3D NAND 堆叠、DRAM 国产化、模组、控制器',
        'keywords': ['HBM', '存储', 'DRAM', 'NAND', '内存', '闪存', '模组', '存储芯片'],
        'industry_alias': ['半导体', '元器件'],
    },
    '人形机器人': {
        'trend': '特斯拉/国产厂商量产爬坡，单台 14 个谐波减速器 + 大量丝杠',
        'bottleneck': '谐波减速器、行星滚柱丝杠、空心杯电机、力矩传感器、PEEK 材料',
        'keywords': ['谐波减速', '减速器', '丝杠', '滚柱', '空心杯', '力矩传感', 'PEEK', '机器人', '电机'],
        'industry_alias': ['机械', '通用设备', '电器机械', '自动化设备', '汽车零部件'],
    },
    '商业航天': {
        'trend': '国家队+民营双轨，发射成本下降 10x 开启低轨星座时代',
        'bottleneck': '火箭发动机、卫星载荷、姿轨控推力器、地面测控、相控阵天线',
        'keywords': ['商业航天', '卫星', '火箭', '发动机', '姿轨控', '推力器', '测控', '相控阵', '航天'],
        'industry_alias': ['航空装备', '航天装备', '国防', '通信设备'],
    },
    '低空经济': {
        'trend': 'eVTOL 适航取证 + 城市空中交通规划落地',
        'bottleneck': '电机电控、碳纤维复材、飞控芯片、动力电池（高功率）',
        'keywords': ['eVTOL', '低空', '飞行汽车', '碳纤维', '复材', '飞控', '通航'],
        'industry_alias': ['航空装备', '通用设备', '汽车零部件'],
    },
    '固态电池': {
        'trend': '全固态电池 2026-2027 量产爬坡，硫化物路线+干法工艺是核心',
        'bottleneck': '硫化物电解质、锂金属负极、干法电极工艺、铝塑膜、硅碳负极',
        'keywords': ['固态电池', '硫化物', '电解质', '锂金属', '干法', '硅碳', '铝塑膜', '负极'],
        'industry_alias': ['电池', '化学制品', '新能源'],
    },
    '可控核聚变': {
        'trend': '中国 BEST/EAST 项目持续推进，2030 前实现净能量增益',
        'bottleneck': '超导磁体（Nb3Sn/ReBCO）、第一壁材料、氚自持、偏滤器、电源系统',
        'keywords': ['核聚变', '超导', '磁体', '第一壁', '偏滤器', 'BEST', 'EAST', 'ITER', '托卡马克'],
        'industry_alias': ['电气设备', '金属新材料', '专用设备', '电源设备'],
    },
    'HBM/先进封装': {
        'trend': 'AI 算力卡 HBM 紧缺 + Chiplet 渗透率提升，封装端价值量翻倍',
        'bottleneck': 'CoWoS/SoIC、ABF 载板、凸块（Bumping）、TSV 硅通孔、玻璃基板',
        'keywords': ['先进封装', 'CoWoS', 'SoIC', 'Chiplet', 'ABF', '载板', '凸块', 'Bumping', 'TSV', '玻璃基板', '封装'],
        'industry_alias': ['半导体', '电子', '元器件'],
    },
    '脑机接口': {
        'trend': 'Neuralink/国内侵入式电极获临床突破，脑机接口进入产业化前夜',
        'bottleneck': '柔性电极、神经信号采集芯片、BCI 整机、低延迟算法',
        'keywords': ['脑机接口', 'BCI', '柔性电极', '神经', '脑电'],
        'industry_alias': ['医疗器械', '医疗', '电子'],
    },
    '铜缆高速连接': {
        'trend': '英伟达 GB200 NVL72 强推铜互联，铜缆/AEC 价值量提升 5x',
        'bottleneck': '高速铜缆、DAC/AEC、连接器、56/112G SerDes',
        'keywords': ['铜缆', 'DAC', 'AEC', '连接器', '高速互联', '112G', 'SerDes'],
        'industry_alias': ['通信设备', '电子', '元器件'],
    },
    '华为鸿蒙': {
        'trend': '鸿蒙原生应用 + 全场景生态落地，PC/汽车/IoT 全面替代',
        'bottleneck': '鸿蒙原生应用开发、鸿蒙 PC、欧拉/昇腾适配、鸿蒙开发工具链',
        'keywords': ['鸿蒙', 'HarmonyOS', '欧拉', '昇腾', '鲲鹏', 'HMS'],
        'industry_alias': ['软件开发', 'IT服务', '计算机', '通信'],
    },
    '数据要素': {
        'trend': '公共数据授权运营落地 + 数据资产入表 + 数字经济立法',
        'bottleneck': '数据交易所、数据确权、可信流通（隐私计算）、数据安全',
        'keywords': ['数据要素', '数据交易', '数据资产', '隐私计算', '数据确权', '数据安全'],
        'industry_alias': ['软件开发', 'IT服务', '计算机', '互联网'],
    },
}


def list_sectors() -> List[str]:
    return list(BOTTLENECK_KB.keys())


def get_bottleneck(sector: str) -> Dict:
    """板块名 → 卡脖子配置；不区分大小写 + 别名匹配"""
    if sector in BOTTLENECK_KB:
        return BOTTLENECK_KB[sector]
    for k, v in BOTTLENECK_KB.items():
        if sector in v.get('industry_alias', []):
            return v
    return {}


def all_keywords() -> List[str]:
    """全量关键词（用于先粗筛全市场股票名）"""
    out = []
    for v in BOTTLENECK_KB.values():
        out.extend(v.get('keywords', []))
    # 去重保序
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def match_sectors_by_keywords(name: str) -> List[str]:
    """股票名 → 命中的所有板块（多对一：一只票可能踩多个热点）"""
    hits = []
    for sector, v in BOTTLENECK_KB.items():
        for kw in v.get('keywords', []):
            if kw in name:
                hits.append(sector)
                break
    return hits


def match_sectors_by_industry(industry: str) -> List[str]:
    """股票行业归属（申万）→ 命中的所有板块"""
    if not industry:
        return []
    hits = []
    for sector, v in BOTTLENECK_KB.items():
        for alias in v.get('industry_alias', []):
            # 模糊匹配：industry 包含 alias 或 alias 包含 industry
            if alias in industry or industry in alias:
                hits.append(sector)
                break
    return hits


def match_sectors(name: str, industry: str = '') -> List[str]:
    """股票 name + industry → 命中的所有板块（双路取并集）"""
    hits = set()
    for s in match_sectors_by_keywords(name):
        hits.add(s)
    for s in match_sectors_by_industry(industry):
        hits.add(s)
    return list(hits)
