"""小米 DDX 每日对比 - 配置文件"""

import os

# ===== 股票配置 =====
STOCK_CODE = os.getenv("STOCK_CODE", "01810")       # 港股代码
STOCK_NAME = os.getenv("STOCK_NAME", "小米集团-W")   # 股票名称
MARKET = os.getenv("MARKET", "HK")                   # 市场：HK=港股

# ===== DDX 计算参数 =====
DDX_LOOKBACK_DAYS = 60  # 回溯天数，用于计算历史对比

# ===== 输出配置 =====
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
CHART_DPI = 150           # 图表分辨率
CHART_FIGSIZE = (14, 8)   # 图表尺寸（英寸）

# ===== 通知渠道（可选）=====
WECHAT_WEBHOOK = os.getenv("WECHAT_WEBHOOK", "")
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS", "")