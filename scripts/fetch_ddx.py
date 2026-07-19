#!/usr/bin/env python3
"""
小米 DDX 每日对比 - 主脚本

功能：
1. 获取港股 K 线数据（东方财富 API）
2. 获取资金流向数据（东方财富 API）
3. 计算 DDX 指标及多周期对比
4. 生成趋势图（PNG）
5. 生成 Markdown 对比报告
6. 发送通知（可选）

数据源：
- 港股行情：东方财富 push2 API（akshare 同源）
- 资金流向：东方财富 push2 API

运行方式：python scripts/fetch_ddx.py
"""

import os
import sys
import json
import argparse
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 设置时区为北京时间（GitHub Actions 默认 UTC）
os.environ['TZ'] = 'Asia/Shanghai'
time_module.tzset()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ============================================================
# 1. 数据获取
# ============================================================

# 东方财富 API 通用请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

# 东方财富 API 通用参数
UT = "bd1d9ddb04089700cf9c27f6f7426281"


def fetch_hk_kline_direct(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    直接通过东方财富 API 获取港股日线 K 线数据
    
    接口: push2his.eastmoney.com/api/qt/stock/kline/get
    参数: secid=116.{symbol} 表示港股
    """
    url = "https://33.push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"116.{symbol}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",           # 101=日线
        "fqt": "1",             # 1=前复权
        "end": "20500000",
        "lmt": str(days + 30),  # 多取一些，确保数据量够
        "ut": UT,
    }
    
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    data = resp.json()
    
    if not data.get("data") or not data["data"].get("klines"):
        print(f"⚠️ 东方财富API返回数据为空: {data.get('data', {}).get('klines')}")
        return None
    
    rows = []
    for line in data["data"]["klines"]:
        parts = line.split(",")
        # f51=日期, f52=开盘, f53=收盘, f54=最高, f55=最低,
        # f56=成交量, f57=成交额, f58=振幅, f59=涨跌幅, f60=涨跌额, f61=换手率
        rows.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "amplitude": float(parts[7]),
            "pct_change": float(parts[8]),
            "change": float(parts[9]),
            "turnover": float(parts[10]),
        })
    
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    return df.tail(days)


def fetch_hk_realtime_quote(symbol: str) -> dict:
    """
    获取港股实时行情（含资金流向数据）
    
    接口: push2.eastmoney.com/api/qt/stock/get
    """
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": f"116.{symbol}",
        "fields": "f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f116,f117,f167,f168,f169,f170,f171",
        "ut": UT,
    }
    
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data"):
            d = data["data"]
            return {
                "price": d.get("f43"),
                "high": d.get("f44"),
                "low": d.get("f45"),
                "open": d.get("f46"),
                "volume": d.get("f47"),
                "amount": d.get("f48"),
                "pct_change": d.get("f170"),
                "change": d.get("f169"),
                "turnover": d.get("f168"),
                "amplitude": d.get("f167"),
            }
    except Exception as e:
        print(f"⚠️ 实时行情获取失败: {e}")
    
    return None


def fetch_hk_individual_fundflow(symbol: str) -> dict:
    """
    获取港股个股资金流向（东方财富DDE决策）
    
    港股资金流向字段：
    f62=主力净流入, f64=超大单净流入, f66=大单净流入,
    f68=中单净流入, f70=小单净流入, f72=主力净流入占比
    f184=成交额, f204=振幅
    """
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": f"116.{symbol}",
        "fields": "f62,f64,f66,f68,f70,f72,f184,f204,f47,f48,f57,f58,f43,f170,f169",
        "ut": UT,
    }
    
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data.get("data"):
            d = data["data"]
            return {
                "main_net_inflow": d.get("f62"),         # 主力净流入
                "super_large_net": d.get("f64"),         # 超大单净流入
                "large_net": d.get("f66"),               # 大单净流入
                "medium_net": d.get("f68"),              # 中单净流入
                "small_net": d.get("f70"),               # 小单净流入
                "main_net_ratio": d.get("f72"),          # 主力净流入占比
                "amount": d.get("f184"),
                "amplitude": d.get("f204"),
                "price": d.get("f43"),
                "pct_change": d.get("f170"),
            }
    except Exception as e:
        print(f"⚠️ 资金流向获取失败: {e}")
    
    return None


def fetch_hk_hist_fundflow(symbol: str, days: int = 60) -> pd.DataFrame:
    """
    获取港股历史K线数据，并计算DDX代理指标
    
    由于港股免费数据无法获取精确的 Level-2 DDX，
    我们基于量价关系计算 DDX 代理指标：
    
    DDX_proxy = 量比 × 涨跌幅 × 振幅因子
    """
    df = fetch_hk_kline_direct(symbol, days)
    if df is None or len(df) < 5:
        return None
    
    # 计算量比（当日成交量/5日均量）
    df["volume_ma5"] = df["volume"].rolling(window=5).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma5"].replace(0, np.nan)
    
    # 振幅因子
    df["amplitude_ma20"] = df["amplitude"].rolling(window=20).mean()
    df["amplitude_factor"] = df["amplitude"] / df["amplitude_ma20"].replace(0, np.nan)
    
    # DDX 代理：量比修正后的价格动量
    # 正数=大单净流入，负数=大单净流出
    df["ddx_raw"] = (
        df["volume_ratio"].fillna(1) * 
        df["pct_change"].fillna(0) * 
        df["amplitude_factor"].fillna(1) / 100
    )
    
    # 标准化到 -1 ~ 1 范围
    std = df["ddx_raw"].std()
    if std > 0:
        df["ddx"] = (df["ddx_raw"] / std * 0.5).clip(-1, 1)
    else:
        df["ddx"] = 0.0
    
    # 累计 DDX
    df["ddx_cum"] = df["ddx"].cumsum()
    
    # 多周期累计
    df["ddx_3"] = df["ddx"].rolling(window=3).sum()
    df["ddx_5"] = df["ddx"].rolling(window=5).sum()
    df["ddx_10"] = df["ddx"].rolling(window=10).sum()
    df["ddx_20"] = df["ddx"].rolling(window=20).sum()
    
    return df


# ============================================================
# 2. 图表生成
# ============================================================

def generate_chart(df: pd.DataFrame, symbol: str, stock_name: str) -> str:
    """
    生成四合一 DDX 趋势图：
    1. 股价走势 + 均线
    2. DDX 柱状图
    3. 累计 DDX
    4. 成交量
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(config.OUTPUT_DIR, f"ddx_chart_{today_str}.png")
    
    fig, axes = plt.subplots(
        4, 1, figsize=config.CHART_FIGSIZE,
        gridspec_kw={"height_ratios": [3, 2, 2, 1.5]},
        sharex=True
    )
    
    dates = df["date"].values
    close_prices = df["close"].values
    ddx = df["ddx"].values
    ddx_cum = df["ddx_cum"].values
    volumes = df["volume"].values
    latest = df.iloc[-1]
    
    # 颜色
    ddx_colors = ["#EF5350" if v >= 0 else "#26A69A" for v in ddx]
    vol_colors = ["#EF5350" if df.iloc[i]["pct_change"] >= 0 else "#26A69A" for i in range(len(df))]
    
    # === 子图 1：股价走势 ===
    ax1 = axes[0]
    ax1.plot(dates, close_prices, color="#1A237E", linewidth=2, label="收盘价", zorder=3)
    ax1.fill_between(dates, close_prices, close_prices.min() * 0.95, alpha=0.08, color="#1A237E")
    
    if len(df) >= 5:
        ma5 = df["close"].rolling(5).mean().values
        ax1.plot(dates, ma5, color="#FF7043", linewidth=1.2, linestyle="--", alpha=0.7, label="MA5")
    if len(df) >= 20:
        ma20 = df["close"].rolling(20).mean().values
        ax1.plot(dates, ma20, color="#42A5F5", linewidth=1.2, linestyle="--", alpha=0.7, label="MA20")
    
    ax1.set_ylabel("价格 (HKD)", fontsize=10)
    ax1.set_title(f"{stock_name} ({symbol}.HK)  DDX 大单动向分析", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)
    
    ax1.annotate(
        f"{latest['close']:.2f}",
        xy=(latest["date"], latest["close"]),
        xytext=(5, 10), textcoords="offset points",
        fontsize=11, fontweight="bold", color="#1A237E"
    )
    
    # === 子图 2：DDX 柱状图 ===
    ax2 = axes[1]
    bars = ax2.bar(dates, ddx, color=ddx_colors, width=0.7, alpha=0.85)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("DDX", fontsize=10)
    ax2.set_title("大单动向 (DDX) — 红柱=净流入  绿柱=净流出", fontsize=10)
    ax2.grid(True, alpha=0.3)
    
    for i in range(max(0, len(df) - 5), len(df)):
        bar = bars[i]
        val = ddx[i]
        if abs(val) > 0.01:
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (0.02 if val >= 0 else -0.08),
                f"{val:.3f}",
                ha="center", va="bottom" if val >= 0 else "top",
                fontsize=7, fontweight="bold",
                color="#EF5350" if val >= 0 else "#26A69A"
            )
    
    # === 子图 3：累计 DDX ===
    ax3 = axes[2]
    ax3.plot(dates, ddx_cum, color="#7B1FA2", linewidth=2, label="累计 DDX")
    ax3.fill_between(dates, ddx_cum, 0, alpha=0.15, color="#7B1FA2")
    ax3.axhline(y=0, color="black", linewidth=0.5)
    ax3.set_ylabel("累计 DDX", fontsize=10)
    ax3.set_title("累计大单动向 — 上升=资金持续流入  下降=资金持续流出", fontsize=10)
    ax3.legend(loc="upper left", fontsize=8)
    ax3.grid(True, alpha=0.3)
    
    # === 子图 4：成交量 ===
    ax4 = axes[3]
    ax4.bar(dates, volumes, color=vol_colors, alpha=0.6, width=0.7)
    ax4.set_ylabel("成交量", fontsize=10)
    ax4.set_title("成交量 (红色=上涨日  绿色=下跌日)", fontsize=10)
    ax4.grid(True, alpha=0.3)
    
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    
    plt.xticks(rotation=30, fontsize=8)
    plt.tight_layout()
    plt.savefig(output_path, dpi=config.CHART_DPI, bbox_inches="tight")
    plt.close()
    
    print(f"✅ 图表已保存: {output_path}")
    return output_path


# ============================================================
# 3. 报告生成
# ============================================================

def generate_report(
    df: pd.DataFrame,
    fundflow: dict,
    quote: dict,
    symbol: str,
    stock_name: str
) -> str:
    """生成 Markdown 格式的 DDX 对比报告"""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
    today_display = today.strftime("%Y-%m-%d")
    output_path = os.path.join(config.OUTPUT_DIR, f"ddx_report_{today_str}.md")
    
    latest = df.iloc[-1]
    
    ddx_now = latest["ddx"]
    ddx_3 = latest["ddx_3"] if not pd.isna(latest.get("ddx_3", np.nan)) else 0
    ddx_5 = latest["ddx_5"] if not pd.isna(latest.get("ddx_5", np.nan)) else 0
    ddx_10 = latest["ddx_10"] if not pd.isna(latest.get("ddx_10", np.nan)) else 0
    ddx_20 = latest["ddx_20"] if not pd.isna(latest.get("ddx_20", np.nan)) else 0
    
    def trend_desc(val, period):
        if val > 0.15:
            return f"大单资金持续净流入，主力积极建仓，短期看多信号"
        elif val > 0.05:
            return f"大单资金小幅流入，主力有试探性买入迹象"
        elif val > -0.05:
            return f"大单资金流向中性，主力无明显动作"
        elif val > -0.15:
            return f"大单资金小幅流出，主力有减仓迹象"
        else:
            return f"大单资金大幅流出，主力持续减仓，注意风险"
    
    # ---- 行情数据 ----
    report = f"""# {stock_name} ({symbol}.HK) DDX 每日对比报告

**生成时间**: {today_display} {today.strftime("%H:%M:%S")}

---

## 📊 今日行情速览

| 指标 | 数值 |
|:-----|:----:|
| 收盘价 | {latest['close']:.2f} HKD |
| 涨跌幅 | {latest['pct_change']:+.2f}% |
| 涨跌额 | {latest['change']:+.4f} HKD |
| 成交量 | {latest['volume'] / 1e8:.2f} 亿股 |
| 成交额 | {latest['amount'] / 1e8:.2f} 亿港元 |
| 振幅 | {latest['amplitude']:.2f}% |
"""
    
    # ---- 资金流向 ----
    if fundflow and fundflow.get("main_net_inflow") is not None:
        main_net = fundflow["main_net_inflow"]
        super_large = fundflow.get("super_large_net", "-")
        large_net = fundflow.get("large_net", "-")
        medium_net = fundflow.get("medium_net", "-")
        small_net = fundflow.get("small_net", "-")
        
        report += f"""
## 💰 实时资金流向

| 类型 | 净额 | 说明 |
|:-----|:---:|:----|
| 主力净流入 | {main_net} | 超大单+大单合计 |
| 超大单净流入 | {super_large} | 机构级资金 |
| 大单净流入 | {large_net} | 游资+大户 |
| 中单净流入 | {medium_net} | 中小投资者 |
| 小单净流入 | {small_net} | 散户资金 |
"""
    
    # ---- DDX 多周期对比 ----
    report += f"""
## 📈 DDX 多周期对比

| 周期 | DDX 累计值 | 趋势判断 |
|:----|:---------:|:--------|
| 今日 | {ddx_now:+.4f} | {trend_desc(ddx_now, '当日')} |
| 近3日 | {ddx_3:+.4f} | {trend_desc(ddx_3, '3日')} |
| 近5日 | {ddx_5:+.4f} | {trend_desc(ddx_5, '5日')} |
| 近10日 | {ddx_10:+.4f} | {trend_desc(ddx_10, '10日')} |
| 近20日 | {ddx_20:+.4f} | {trend_desc(ddx_20, '20日')} |

## 📉 趋势判断

### 短期（1-3日）
{trend_desc(ddx_3, '3日')}

### 中期（5-10日）
{trend_desc(ddx_10, '10日')}

### 长期（20日）
{trend_desc(ddx_20, '20日')}

## 📋 近5日明细

| 日期 | 收盘价 | 涨跌幅 | DDX | 成交量(亿) |
|:---|:-----:|:-----:|:---:|:--------:|
"""
    
    recent = df.tail(5)
    for _, row in recent.iterrows():
        d = row["date"].strftime("%m-%d")
        report += f"| {d} | {row['close']:.2f} | {row['pct_change']:+.2f}% | {row['ddx']:+.4f} | {row['volume'] / 1e8:.2f} |\n"
    
    report += f"""
---

## ⚠️ 免责声明

> 本报告由 GitHub Actions 自动生成，数据来源于东方财富公开免费接口。
> DDX 指标为基于公开量价数据的近似计算，不构成投资建议。
> 股市有风险，投资需谨慎。
"""
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"✅ 报告已保存: {output_path}")
    return output_path


# ============================================================
# 4. 通知推送
# ============================================================

def send_notifications(report_path: str, chart_path: str):
    """发送通知到配置的渠道"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    if config.WECHAT_WEBHOOK:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            preview = content[:2000]
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"# 小米 DDX 每日对比 ({today})\n\n{preview}"
                }
            }
            requests.post(config.WECHAT_WEBHOOK, json=payload, timeout=10)
            print("✅ 企业微信通知已发送")
        except Exception as e:
            print(f"⚠️ 企业微信通知失败: {e}")
    
    if config.FEISHU_WEBHOOK:
        try:
            payload = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": f"小米 DDX 每日对比 ({today})",
                            "content": [[{"tag": "text", "text": f"报告已生成，请查看 output/ 目录"}]]
                        }
                    }
                }
            }
            requests.post(config.FEISHU_WEBHOOK, json=payload, timeout=10)
            print("✅ 飞书通知已发送")
        except Exception as e:
            print(f"⚠️ 飞书通知失败: {e}")


# ============================================================
# 5. 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="小米 DDX 每日对比")
    parser.add_argument("--code", default=config.STOCK_CODE, help="港股代码")
    parser.add_argument("--name", default=config.STOCK_NAME, help="股票名称")
    parser.add_argument("--days", type=int, default=config.DDX_LOOKBACK_DAYS, help="回溯天数")
    parser.add_argument("--no-chart", action="store_true", help="跳过图表生成")
    args = parser.parse_args()
    
    print("=" * 60)
    print(f"  小米 DDX 每日对比 - {args.name} ({args.code}.HK)")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Step 1: 获取实时行情
    print("\n📡 获取实时行情...")
    quote = fetch_hk_realtime_quote(args.code)
    if quote:
        print(f"   最新价: {quote.get('price')}  涨跌幅: {quote.get('pct_change')}%")
    else:
        print("   ⚠️ 实时行情不可用")
    
    # Step 2: 获取资金流向
    print("\n💰 获取资金流向数据...")
    fundflow = fetch_hk_individual_fundflow(args.code)
    if fundflow:
        print(f"   主力净流入: {fundflow.get('main_net_inflow')}")
    else:
        print("   ⚠️ 资金流向数据不可用")
    
    # Step 3: 获取历史K线并计算 DDX
    print("\n📊 获取历史K线数据并计算 DDX...")
    df = fetch_hk_hist_fundflow(args.code, days=args.days)
    if df is None or len(df) < 2:
        print("❌ 无法获取数据，请检查网络或股票代码")
        sys.exit(1)
    
    print(f"   ✅ 获取 {len(df)} 个交易日数据")
    print(f"   最新日期: {df.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"   最新收盘: {df.iloc[-1]['close']:.2f}")
    print(f"   最新 DDX: {df.iloc[-1]['ddx']:+.4f}")
    
    # Step 4: 生成图表
    if not args.no_chart:
        print("\n🖼️ 生成 DDX 趋势图...")
        chart_path = generate_chart(df, args.code, args.name)
    else:
        chart_path = None
    
    # Step 5: 生成报告
    print("\n📝 生成对比报告...")
    report_path = generate_report(df, fundflow, quote, args.code, args.name)
    
    # Step 6: 发送通知
    if config.WECHAT_WEBHOOK or config.FEISHU_WEBHOOK:
        print("\n🔔 发送通知...")
        send_notifications(report_path, chart_path)
    
    print("\n" + "=" * 60)
    print("  ✅ 完成！")
    print(f"  📄 报告: {report_path}")
    if chart_path:
        print(f"  🖼️  图表: {chart_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()