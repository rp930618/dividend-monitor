#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================
v8.2 渐进式建仓版红利策略监测脚本
========================================
功能流程：数据获取 → 因子计算 → 评分 → 风控 → 权重重分配 → ERP现金管理
         → 渐进式建仓(4批次) / 混合信号调仓(L1/L2/L3/时间保底) → DDCA检查 → 报告推送

建仓方案（v8.2核心改进）：
  · 第1批（首日）：30%，立即执行
  · 第2批（5天后）：30%，或较首仓下跌3%提前触发
  · 第3批（10天后）：25%，或较首仓下跌5%提前触发
  · 第4批（20天后）：15%，尾仓收尾
  · 建仓期间评分<35暂停，触发清仓立即停止
  · 建仓完成后进入持有期（L1+L2+L3+时间保底）
"""

import os
import sys
import json
import math
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import requests
import numpy as np
import pandas as pd

# 尝试导入AKShare，如失败则标记
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except Exception:
    AKSHARE_AVAILABLE = False

# 尝试导入yfinance（海外环境备用数据源）
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:
    YFINANCE_AVAILABLE = False


# ============================================
# 0. 静态兜底数据（AKShare获取失败时使用）
# ============================================
STATIC_FALLBACK_DATA = {
    "600036": {
        "name": "招商银行", "price": 35.0, "dividend_yield": 0.045,
        "roe": 0.15, "roe_std_3y": 0.008, "cashflow_to_debt": 0.25,
        "pe_ttm": 6.5, "volatility_250d": 0.18, "earnings_growth": 0.06,
        "net_profit_history": [1200e8, 1300e8, 1400e8],
        "operating_cashflow_history": [200e8, 250e8, 300e8],
        "payout_ratio": 0.32, "is_st": False, "dividend_cut": False,
    },
    "600900": {
        "name": "长江电力", "price": 28.5, "dividend_yield": 0.038,
        "roe": 0.12, "roe_std_3y": 0.005, "cashflow_to_debt": 0.40,
        "pe_ttm": 20.0, "volatility_250d": 0.14, "earnings_growth": 0.03,
        "net_profit_history": [260e8, 270e8, 280e8],
        "operating_cashflow_history": [400e8, 420e8, 450e8],
        "payout_ratio": 0.65, "is_st": False, "dividend_cut": False,
    },

    "000651": {
        "name": "格力电器", "price": 42.0, "dividend_yield": 0.055,
        "roe": 0.22, "roe_std_3y": 0.012, "cashflow_to_debt": 0.35,
        "pe_ttm": 8.0, "volatility_250d": 0.20, "earnings_growth": 0.04,
        "net_profit_history": [230e8, 245e8, 260e8],
        "operating_cashflow_history": [280e8, 300e8, 320e8],
        "payout_ratio": 0.50, "is_st": False, "dividend_cut": False,
    },
    "601668": {
        "name": "中国建筑", "price": 5.8, "dividend_yield": 0.048,
        "roe": 0.10, "roe_std_3y": 0.006, "cashflow_to_debt": 0.18,
        "pe_ttm": 4.5, "volatility_250d": 0.16, "earnings_growth": 0.08,
        "net_profit_history": [500e8, 540e8, 580e8],
        "operating_cashflow_history": [100e8, 80e8, 120e8],
        "payout_ratio": 0.20, "is_st": False, "dividend_cut": False,
    },
    "600941": {
        "name": "中国移动", "price": 105.0, "dividend_yield": 0.040,
        "roe": 0.09, "roe_std_3y": 0.004, "cashflow_to_debt": 0.55,
        "pe_ttm": 16.0, "volatility_250d": 0.15, "earnings_growth": 0.05,
        "net_profit_history": [1100e8, 1150e8, 1200e8],
        "operating_cashflow_history": [1500e8, 1600e8, 1700e8],
        "payout_ratio": 0.60, "is_st": False, "dividend_cut": False,
    },
    "601006": {
        "name": "大秦铁路", "price": 7.0, "dividend_yield": 0.058,
        "roe": 0.09, "roe_std_3y": 0.010, "cashflow_to_debt": 0.22,
        "pe_ttm": 7.5, "volatility_250d": 0.13, "earnings_growth": -0.01,
        "net_profit_history": [120e8, 115e8, 110e8],
        "operating_cashflow_history": [150e8, 140e8, 130e8],
        "payout_ratio": 0.58, "is_st": False, "dividend_cut": False,
    },
    "000895": {
        "name": "双汇发展", "price": 26.0, "dividend_yield": 0.052,
        "roe": 0.28, "roe_std_3y": 0.015, "cashflow_to_debt": 0.45,
        "pe_ttm": 17.0, "volatility_250d": 0.19, "earnings_growth": -0.03,
        "net_profit_history": [55e8, 52e8, 50e8],
        "operating_cashflow_history": [60e8, 55e8, 50e8],
        "payout_ratio": 0.75, "is_st": False, "dividend_cut": False,
    },
    "515450": {
        "name": "红利低波ETF", "price": 1.25, "dividend_yield": 0.045,
        "roe": 0.10, "roe_std_3y": 0.020, "cashflow_to_debt": 0.30,
        "pe_ttm": 7.0, "volatility_250d": 0.14, "earnings_growth": 0.02,
        "net_profit_history": [None, None, None],
        "operating_cashflow_history": [None, None, None],
        "payout_ratio": 0.50, "is_st": False, "dividend_cut": False,
    },
    "CASH": {
        "name": "现金", "price": 1.0, "dividend_yield": 0.015,
        "roe": 0.0, "roe_std_3y": 0.0, "cashflow_to_debt": 1.0,
        "pe_ttm": 999.0, "volatility_250d": 0.0, "earnings_growth": 0.0,
        "net_profit_history": [None, None, None],
        "operating_cashflow_history": [None, None, None],
        "payout_ratio": 0.0, "is_st": False, "dividend_cut": False,
    },
}

# 模拟持股天数（实际应从交易记录读取，此处用配置起始日推算）
HOLDING_START_DATE = datetime(2023, 7, 1)


# ============================================
# 1. 数据类定义
# ============================================
@dataclass
class HoldingConfig:
    code: str
    name: str
    target_weight: float
    target_amount: float
    type: str
    min_lots: int
    exchange: str


@dataclass
class FactorData:
    code: str
    name: str
    price: float = 0.0
    dividend_yield: float = 0.0
    roe: float = 0.0
    roe_std_3y: float = 0.0
    cashflow_to_debt: float = 0.0
    pe_ttm: float = 0.0
    volatility_250d: float = 0.0
    earnings_growth: float = 0.0
    net_profit_history: List[Optional[float]] = field(default_factory=list)
    operating_cashflow_history: List[Optional[float]] = field(default_factory=list)
    payout_ratio: float = 0.0
    is_st: bool = False
    dividend_cut: bool = False


@dataclass
class ScoreResult:
    code: str
    name: str
    total_score: float = 0.0
    factor_scores: Dict[str, float] = field(default_factory=dict)
    target_position_pct: float = 0.0


@dataclass
class RiskSignal:
    code: str
    signal_type: str  # 'clear', 'reduce', 'observe', 'warning'
    reason: str
    severity: int  # 1-5, 5最高


@dataclass
class TradeSignal:
    code: str
    name: str
    action: str  # 'buy', 'sell', 'hold', 'clear', 'ddca_add'
    reason: str
    suggested_amount: float = 0.0


# ============================================
# 2. 主监控类
# ============================================
class DividendMonitor:
    def __init__(self, config_path: str = "config.yaml"):
        self.script_dir = Path(__file__).parent.resolve()
        self.config = self._load_config(config_path)
        self.setup_logging()
        self.logger = logging.getLogger("DividendMonitor")
        self.holdings: List[HoldingConfig] = []
        self._parse_holdings()
        self.factor_data: Dict[str, FactorData] = {}
        self.score_results: Dict[str, ScoreResult] = {}
        self.risk_signals: List[RiskSignal] = []
        self.trade_signals: List[TradeSignal] = []
        self.state: Dict[str, Any] = {
            "last_reduce_date": {},
            "observation_until": {},
            "dividend_yield_low_days": {},
            "portfolio_dy_low_days": 0,
            "cash_pool": self.config.get("total_capital", 405000) * 0.05,
            "current_weights": {h.code: h.target_weight for h in self.holdings},
            "holding_days": {},
            # === 混合信号调仓状态 ===
            "valuation_history": [],           # [{date, portfolio_pe, portfolio_dy}, ...]
            "deviation_streaks": {},           # code -> 连续偏离天数
            "l1_cooldown_until": {},           # code -> "YYYY-MM-DD"
            "level2_streak": 0,                # L2条件连续天数
            "level2_direction": None,          # "overvalued" | "undervalued" | None
            "last_comprehensive_check": None,  # "YYYY-MM-DD"
            "trading_day_counter": 0,          # 建仓后累计交易日
            "first_build_completed": False,    # 首次建仓是否完成
        }
        self.is_first_run = not (self.script_dir / "monitor_state.json").exists()
        self._init_state()
        self._load_persistent_state()
        self.logger.info("DividendMonitor v8 初始化完成")
        if self.is_first_run:
            self.logger.info("【首次运行】检测到无历史状态，将生成全面建仓信号")

    def _load_config(self, config_path: str) -> dict:
        cfg_file = self.script_dir / config_path
        if not cfg_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {cfg_file}")
        with open(cfg_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def setup_logging(self):
        log_cfg = self.config.get("logging", {})
        level = getattr(logging, log_cfg.get("level", "INFO"), logging.INFO)
        fmt = log_cfg.get("format", "%(asctime)s [%(levelname)s] %(message)s")
        log_file = self.script_dir / log_cfg.get("file", "dividend_monitor.log")
        handlers = [logging.StreamHandler(sys.stdout)]
        try:
            from logging.handlers import RotatingFileHandler
            fh = RotatingFileHandler(
                log_file, maxBytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
                backupCount=log_cfg.get("backup_count", 5), encoding="utf-8"
            )
            handlers.append(fh)
        except Exception:
            pass
        logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)

    def _parse_holdings(self):
        for item in self.config.get("holdings", []):
            self.holdings.append(HoldingConfig(
                code=item["code"],
                name=item["name"],
                target_weight=item["target_weight"],
                target_amount=item["target_amount"],
                type=item["type"],
                min_lots=item["min_lots"],
                exchange=item.get("exchange", ""),
            ))

    def _init_state(self):
        is_fresh_start = self.is_first_run
        for h in self.holdings:
            self.state["last_reduce_date"][h.code] = None
            self.state["observation_until"][h.code] = None
            self.state["dividend_yield_low_days"][h.code] = 0
            if is_fresh_start:
                self.state["holding_days"][h.code] = 0
            elif h.code not in self.state["holding_days"]:
                self.state["holding_days"][h.code] = max(0, (datetime.now() - HOLDING_START_DATE).days)

    # -------------------------------------------------
    # 2.0 持久化状态管理（估值历史等）
    # -------------------------------------------------
    def _load_persistent_state(self):
        state_file = self.script_dir / "monitor_state.json"
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    persistent = json.load(f)
                for key in ["valuation_history", "deviation_streaks", "l1_cooldown_until",
                            "level2_streak", "level2_direction", "last_comprehensive_check",
                            "trading_day_counter"]:
                    if key in persistent:
                        self.state[key] = persistent[key]
                self.logger.info(f"已加载持久化状态: {len(self.state['valuation_history'])}条估值历史")
            except Exception as e:
                self.logger.warning(f"加载持久化状态失败: {e}")

    def _save_persistent_state(self):
        state_file = self.script_dir / "monitor_state.json"
        try:
            persistent = {
                "valuation_history": self.state["valuation_history"],
                "deviation_streaks": self.state["deviation_streaks"],
                "l1_cooldown_until": self.state["l1_cooldown_until"],
                "level2_streak": self.state["level2_streak"],
                "level2_direction": self.state["level2_direction"],
                "last_comprehensive_check": self.state["last_comprehensive_check"],
                "trading_day_counter": self.state["trading_day_counter"],
            }
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(persistent, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            self.logger.warning(f"保存持久化状态失败: {e}")

    # -------------------------------------------------
    # 2.1 数据获取
    # -------------------------------------------------
    def fetch_data(self):
        self.logger.info("===== 开始数据获取 =====")
        fallback = self.config.get("data", {}).get("fallback_to_static", True)
        data_source_stats = {"akshare": 0, "yfinance": 0, "static": 0}
        for h in self.holdings:
            if h.type == "cash":
                self.factor_data[h.code] = self._get_static_data(h.code)
                continue

            fd = None

            # 优先尝试AKShare（国内环境最佳）
            if AKSHARE_AVAILABLE:
                try:
                    fd = self._fetch_akshare_data(h)
                    data_source_stats["akshare"] += 1
                    self.logger.info(f"[{h.code}] AKShare数据获取成功: 价格={fd.price:.2f}, DY={fd.dividend_yield:.2%}")
                except Exception as e:
                    self.logger.warning(f"[{h.code}] AKShare获取失败: {e}")

            # AKShare失败，尝试yfinance（海外环境稳定）
            if fd is None and YFINANCE_AVAILABLE:
                try:
                    fd = self._fetch_yfinance_data(h)
                    data_source_stats["yfinance"] += 1
                    self.logger.info(f"[{h.code}] yfinance数据获取成功: 价格={fd.price:.2f}, DY={fd.dividend_yield:.2%}")
                except Exception as e:
                    self.logger.warning(f"[{h.code}] yfinance获取失败: {e}")

            # 都失败，用静态兜底
            if fd is None:
                if fallback:
                    fd = self._get_static_data(h.code)
                    data_source_stats["static"] += 1
                    self.logger.info(f"[{h.code}] 已切换至静态兜底数据")
                else:
                    fd = FactorData(code=h.code, name=h.name)

            self.factor_data[h.code] = fd

        self.logger.info(f"===== 数据获取完成: AKShare={data_source_stats['akshare']}成功, yfinance={data_source_stats['yfinance']}成功, 静态={data_source_stats['static']}兜底 =====")

    def _fetch_yfinance_data(self, h: HoldingConfig) -> FactorData:
        """通过yfinance获取数据（海外环境稳定备用）"""
        fd = FactorData(code=h.code, name=h.name)
        # yfinance A股代码格式：600036.SS（上海）或 000651.SZ（深圳）
        # ETF代码格式：515450.SS
        if h.exchange == "sh":
            yf_code = h.code + ".SS"
        elif h.exchange == "sz":
            yf_code = h.code + ".SZ"
        else:
            yf_code = h.code + ".SS"  # 默认上海

        end_date = datetime.now()
        start_date = end_date - timedelta(days=400)

        ticker = yf.Ticker(yf_code)
        df_hist = ticker.history(start=start_date, end=end_date)

        if df_hist is None or df_hist.empty:
            raise ValueError(f"yfinance历史数据为空: {yf_code}")

        fd.price = float(df_hist["Close"].iloc[-1])

        # 计算波动率
        returns = df_hist["Close"].pct_change().dropna()
        fd.volatility_250d = float(returns.tail(min(250, len(returns))).std() * math.sqrt(252)) if len(returns) >= 20 else 0.20

        # 获取分红数据
        divs = ticker.dividends
        if divs is not None and not divs.empty and len(divs) > 0:
            # 取最近一年分红总和
            one_year_ago = end_date - timedelta(days=365)
            recent_divs = divs[divs.index >= one_year_ago]
            total_div = float(recent_divs.sum())
            fd.dividend_yield = total_div / fd.price if fd.price > 0 else 0.04
        else:
            # 从静态数据获取股息率
            static = STATIC_FALLBACK_DATA.get(h.code)
            fd.dividend_yield = static["dividend_yield"] if static else 0.04

        # 获取基本信息（PE、ROE等）
        info = ticker.info
        if info:
            fd.pe_ttm = float(info.get("trailingPE", 15.0) or 15.0)
            fd.roe = float(info.get("returnOnEquity", 0.10) or 0.10)
        else:
            fd.pe_ttm = 15.0
            fd.roe = 0.10

        # 其他因子用估算值
        fd.roe_std_3y = 0.01
        fd.cashflow_to_debt = 0.30
        fd.earnings_growth = 0.03
        fd.net_profit_history = [None, None, None]
        fd.operating_cashflow_history = [None, None, None]
        fd.payout_ratio = 0.50
        fd.is_st = False
        fd.dividend_cut = False

        return fd

    def _fetch_akshare_data(self, h: HoldingConfig) -> FactorData:
        fd = FactorData(code=h.code, name=h.name)
        if not AKSHARE_AVAILABLE:
            raise RuntimeError("AKShare未安装")

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")

        if h.type == "stock":
            df_hist = ak.stock_zh_a_hist(
                symbol=h.code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
            )
        else:
            df_hist = ak.fund_etf_hist_em(
                symbol=h.code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
            )

        if df_hist is None or df_hist.empty:
            raise ValueError("历史行情为空")

        df_hist["日期"] = pd.to_datetime(df_hist["日期"])
        df_hist = df_hist.sort_values("日期")
        fd.price = float(df_hist["收盘"].iloc[-1])

        returns = df_hist["收盘"].pct_change().dropna()
        fd.volatility_250d = float(returns.tail(250).std() * math.sqrt(252)) if len(returns) >= 20 else 0.20

        try:
            if h.type == "stock":
                fin = ak.stock_financial_analysis_indicator(symbol=h.code)
                if fin is not None and not fin.empty:
                    latest = fin.iloc[0]
                    fd.roe = self._safe_float(latest.get("净资产收益率")) / 100 if "净资产收益率" in fin.columns else 0.10
                    fd.pe_ttm = self._safe_float(latest.get("市盈率")) if "市盈率" in fin.columns else 15.0
            else:
                fd.roe = 0.10
                fd.pe_ttm = 10.0
        except Exception:
            fd.roe = 0.10
            fd.pe_ttm = 15.0

        fd.dividend_yield = self._estimate_dividend_yield(h.code, fd.price, df_hist)
        fd.roe_std_3y = 0.01
        fd.cashflow_to_debt = 0.30
        fd.earnings_growth = 0.03
        fd.net_profit_history = [None, None, None]
        fd.operating_cashflow_history = [None, None, None]
        fd.payout_ratio = 0.50
        fd.is_st = False
        fd.dividend_cut = False
        return fd

    def _safe_float(self, val) -> float:
        try:
            return float(val)
        except Exception:
            return 0.0

    def _estimate_dividend_yield(self, code: str, price: float, df_hist: pd.DataFrame) -> float:
        try:
            if code.startswith("515") or code.startswith("51") or code.startswith("15") or code.startswith("16"):
                return 0.045
            div_df = ak.stock_dividend_cninfo(symbol=code)
            if div_df is not None and not div_df.empty:
                latest_div = div_df.iloc[0]
                cash_div = self._safe_float(latest_div.get("每股派息"))
                if cash_div > 0 and price > 0:
                    return cash_div / price
        except Exception:
            pass
        return 0.04

    def _get_static_data(self, code: str) -> FactorData:
        d = STATIC_FALLBACK_DATA.get(code, STATIC_FALLBACK_DATA["CASH"])
        return FactorData(
            code=code, name=d["name"], price=d["price"], dividend_yield=d["dividend_yield"],
            roe=d["roe"], roe_std_3y=d["roe_std_3y"], cashflow_to_debt=d["cashflow_to_debt"],
            pe_ttm=d["pe_ttm"], volatility_250d=d["volatility_250d"], earnings_growth=d["earnings_growth"],
            net_profit_history=d["net_profit_history"],
            operating_cashflow_history=d["operating_cashflow_history"],
            payout_ratio=d["payout_ratio"], is_st=d["is_st"], dividend_cut=d["dividend_cut"],
        )

    def fetch_erp(self) -> float:
        try:
            if AKSHARE_AVAILABLE:
                rate_df = ak.bond_zh_us_rate()
                if rate_df is not None and not rate_df.empty and "中国国债收益率10年" in rate_df.columns:
                    rf = float(rate_df["中国国债收益率10年"].dropna().iloc[-1]) / 100
                else:
                    rf = 0.025
            else:
                rf = 0.025
        except Exception:
            rf = 0.025
        try:
            if AKSHARE_AVAILABLE:
                val_df = ak.index_value_hist_funddb(symbol="上证指数")
                if val_df is not None and not val_df.empty and "市盈率" in val_df.columns:
                    pe = float(val_df["市盈率"].dropna().iloc[-1])
                else:
                    pe = 13.0
            else:
                pe = 13.0
        except Exception:
            pe = 13.0
        earnings_yield = 1.0 / pe if pe > 0 else 0.07
        erp = earnings_yield - rf
        self.logger.info(f"ERP计算: 盈利收益率={earnings_yield:.2%}, 无风险利率={rf:.2%}, ERP={erp:.2%}")
        return erp

    # -------------------------------------------------
    # 2.2 因子计算与评分
    # -------------------------------------------------
    def compute_factors_and_score(self):
        self.logger.info("===== 开始因子计算与评分 =====")
        weights = self.config.get("scoring_weights", {})
        preprocess = self.config.get("factor_preprocess", {})
        win_low = preprocess.get("winsorize_lower", 0.01)
        win_high = preprocess.get("winsorize_upper", 0.99)

        raw_factors = []
        for code, fd in self.factor_data.items():
            if fd.code == "CASH":
                continue
            raw_factors.append({
                "code": code, "dividend_yield": fd.dividend_yield,
                "roe": fd.roe, "roe_stability": 1.0 / (1.0 + fd.roe_std_3y * 10),
                "cashflow_to_debt": fd.cashflow_to_debt,
                "pe_valuation": fd.pe_ttm, "volatility": fd.volatility_250d,
                "earnings_growth": fd.earnings_growth,
            })

        df_factors = pd.DataFrame(raw_factors)
        if df_factors.empty:
            self.logger.warning("因子数据为空，跳过评分")
            return

        numeric_cols = ["dividend_yield", "roe", "roe_stability", "cashflow_to_debt", "pe_valuation", "volatility", "earnings_growth"]
        for col in numeric_cols:
            df_factors[col] = pd.to_numeric(df_factors[col], errors="coerce").fillna(df_factors[col].median())

        for col in numeric_cols:
            low, high = df_factors[col].quantile([win_low, win_high])
            df_factors[col] = df_factors[col].clip(lower=low, upper=high)

        zscore_cols = ["dividend_yield", "roe", "roe_stability", "cashflow_to_debt", "earnings_growth"]
        for col in zscore_cols:
            mean = df_factors[col].mean()
            std = df_factors[col].std()
            df_factors[f"{col}_z"] = ((df_factors[col] - mean) / std) if std > 0 else 0.0

        pe_mean = df_factors["pe_valuation"].mean()
        pe_std = df_factors["pe_valuation"].std()
        df_factors["pe_valuation_z"] = -((df_factors["pe_valuation"] - pe_mean) / pe_std) if pe_std > 0 else 0.0

        vol_mean = df_factors["volatility"].mean()
        vol_std = df_factors["volatility"].std()
        df_factors["volatility_z"] = -((df_factors["volatility"] - vol_mean) / vol_std) if vol_std > 0 else 0.0

        for _, row in df_factors.iterrows():
            code = row["code"]
            fd = self.factor_data[code]
            scores = {}
            scores["dividend_yield"] = self._zscore_to_score(row["dividend_yield_z"]) * weights.get("dividend_yield", 25) / 100
            scores["roe_level"] = self._zscore_to_score(row["roe_z"]) * weights.get("roe_level", 20) / 100
            scores["roe_stability"] = self._zscore_to_score(row["roe_stability_z"]) * weights.get("roe_stability", 15) / 100
            scores["cashflow_to_debt"] = self._zscore_to_score(row["cashflow_to_debt_z"]) * weights.get("cashflow_to_debt", 15) / 100
            scores["pe_valuation"] = self._zscore_to_score(row["pe_valuation_z"]) * weights.get("pe_valuation", 10) / 100
            scores["low_volatility"] = self._zscore_to_score(row["volatility_z"]) * weights.get("low_volatility", 10) / 100
            scores["earnings_growth"] = self._zscore_to_score(row["earnings_growth_z"]) * weights.get("earnings_growth", 5) / 100

            total = sum(scores.values())
            total = max(0.0, min(100.0, total * 100))
            target_pos = self._score_to_position(total)

            sr = ScoreResult(code=code, name=fd.name, total_score=total, factor_scores=scores, target_position_pct=target_pos)
            self.score_results[code] = sr
            self.logger.info(f"[{code}] 评分={total:.1f}, 目标仓位={target_pos:.0%}, 因子={scores}")

        self.logger.info("===== 因子计算与评分完成 =====")

    def _zscore_to_score(self, z: float) -> float:
        return max(0.0, min(1.0, 0.5 + z * 0.3))

    def _score_to_position(self, score: float) -> float:
        mapping = self.config.get("score_to_position", [])
        mapping = sorted(mapping, key=lambda x: x["min_score"], reverse=True)
        for item in mapping:
            if score >= item["min_score"]:
                return item["position_pct"]
        return 0.0

    # -------------------------------------------------
    # 2.3 容差检查（5/25规则）
    # -------------------------------------------------
    def check_tolerance(self) -> List[TradeSignal]:
        self.logger.info("===== 开始容差检查（5/25规则） =====")
        signals = []
        tol = self.config.get("tolerance", {})
        abs_tol = tol.get("absolute_pct", 0.05)
        rel_tol = tol.get("relative_pct", 0.25)
        total = self.config.get("total_capital", 405000)
        today = datetime.now().date()

        for h in self.holdings:
            if h.code == "CASH":
                continue
            # 排除处于观察期或被风控清仓的标的
            obs = self.state["observation_until"].get(h.code)
            if obs:
                obs_date = datetime.strptime(obs, "%Y-%m-%d").date() if isinstance(obs, str) else obs
                if today < obs_date:
                    self.logger.info(f"[{h.code}] 处于观察期，跳过容差检查")
                    continue
            if self.state["current_weights"].get(h.code, 0) <= 0 and h.target_weight > 0:
                # 已清仓标的不再产生买入容差信号（除非观察期结束且评分恢复）
                sr = self.score_results.get(h.code)
                if sr and sr.total_score < 30:
                    self.logger.info(f"[{h.code}] 当前已清仓且评分较低，跳过买入容差检查")
                    continue
            current_w = self.state["current_weights"].get(h.code, h.target_weight)
            target_w = h.target_weight
            diff = abs(current_w - target_w)
            rel_diff = diff / target_w if target_w > 0 else 0
            threshold = min(abs_tol, target_w * rel_tol)
            self.logger.info(f"[{h.code}] 当前权重={current_w:.2%}, 目标权重={target_w:.2%}, 偏差={diff:.2%}, 阈值={threshold:.2%}")
            if diff > threshold:
                if current_w < target_w:
                    action = "buy"
                    amount = (target_w - current_w) * total
                else:
                    action = "sell"
                    amount = (current_w - target_w) * total
                signals.append(TradeSignal(
                    code=h.code, name=h.name, action=action,
                    reason=f"5/25容差超限: 偏差{diff:.2%} > 阈值{threshold:.2%}",
                    suggested_amount=amount
                ))
                self.logger.info(f"[{h.code}] 容差信号: {action} {amount:.0f}元")
        self.logger.info(f"容差检查完成，发现{len(signals)}个信号")
        return signals

    # -------------------------------------------------
    # 2.4 风控检查
    # -------------------------------------------------
    def check_risk_control(self) -> List[RiskSignal]:
        self.logger.info("===== 开始风控红线检查 =====")
        signals = []
        rc = self.config.get("risk_control", {})
        red = rc.get("red_lines", {})
        dy_risk = rc.get("dividend_yield_risk", {})
        cooldown = rc.get("cooldown_days", 10)
        today = datetime.now().date()

        for h in self.holdings:
            if h.type == "cash":
                continue
            fd = self.factor_data.get(h.code)
            if fd is None:
                continue

            if self.state["observation_until"].get(h.code):
                obs_until = datetime.strptime(self.state["observation_until"][h.code], "%Y-%m-%d").date() if isinstance(self.state["observation_until"][h.code], str) else self.state["observation_until"][h.code]
                if today < obs_until:
                    self.logger.info(f"[{h.code}] 处于观察期，跳过")
                    continue
                else:
                    self.logger.info(f"[{h.code}] 观察期结束")
                    self.state["observation_until"][h.code] = None

            reasons = []
            if red.get("st_status_flag", True) and fd.is_st:
                reasons.append("ST状态")
            if red.get("dividend_cut_flag", True) and fd.dividend_cut:
                reasons.append("分红削减/中断")
            if fd.roe < red.get("roe_below_threshold", 0.08):
                reasons.append(f"ROE<{red.get('roe_below_threshold', 0.08):.0%}")
            np_hist = [x for x in fd.net_profit_history if x is not None]
            if len(np_hist) >= 2:
                declines = 0
                for i in range(1, min(red.get("net_profit_consecutive_years", 2), len(np_hist))):
                    if np_hist[i] < np_hist[i - 1] * (1 - red.get("net_profit_decline_pct", 0.10)):
                        declines += 1
                if declines >= red.get("net_profit_consecutive_years", 2) - 1:
                    reasons.append(f"净利润连续下降>{red.get('net_profit_decline_pct', 0.10):.0%}")
            cf_hist = [x for x in fd.operating_cashflow_history if x is not None]
            neg_years = sum(1 for x in cf_hist if x < 0)
            if neg_years >= red.get("operating_cashflow_consecutive_years", 2):
                reasons.append("经营现金流连续为负")
            if red.get("payout_with_earnings_decline", True):
                if fd.payout_ratio > red.get("payout_ratio_threshold", 0.80):
                    if np_hist and len(np_hist) >= 2 and np_hist[0] < np_hist[1]:
                        reasons.append("分红率>80%且盈利下降")

            if reasons:
                sig = RiskSignal(code=h.code, signal_type="clear", reason=";".join(reasons), severity=5)
                signals.append(sig)
                self.state["observation_until"][h.code] = today + timedelta(days=rc.get("observation_period_days", 90))
                self.logger.warning(f"[{h.code}] 触发清仓红线: {sig.reason}, 观察期至{self.state['observation_until'][h.code]}")

            single_dy_th = dy_risk.get("single_below_threshold", 0.03)
            single_days_th = dy_risk.get("single_consecutive_days", 10)
            if fd.dividend_yield < single_dy_th:
                self.state["dividend_yield_low_days"][h.code] = self.state["dividend_yield_low_days"].get(h.code, 0) + 1
                if self.state["dividend_yield_low_days"][h.code] >= single_days_th:
                    sig = RiskSignal(code=h.code, signal_type="clear", reason=f"股息率<{single_dy_th:.1%}连续{single_days_th}天", severity=5)
                    signals.append(sig)
                    self.logger.warning(f"[{h.code}] 触发股息率清仓: {sig.reason}")
            else:
                self.state["dividend_yield_low_days"][h.code] = 0

            last_reduce = self.state["last_reduce_date"].get(h.code)
            if last_reduce and (today - last_reduce).days < cooldown:
                continue

        try:
            self._check_portfolio_dividend_yield_risk(signals)
        except Exception as e:
            self.logger.error(f"组合股息率风控检查异常: {e}")

        self.risk_signals = signals
        self.logger.info(f"===== 风控检查完成，发现{len(signals)}个信号 =====")
        return signals

    def _check_portfolio_dividend_yield_risk(self, signals: List[RiskSignal]):
        dy_risk = self.config.get("risk_control", {}).get("dividend_yield_risk", {})
        equity_codes = [h.code for h in self.holdings if h.type != "cash"]
        if not equity_codes:
            return
        total_w = sum(self.state["current_weights"].get(c, 0) for c in equity_codes)
        portfolio_dy = 0.0
        for c in equity_codes:
            w = self.state["current_weights"].get(c, 0)
            dy = self.factor_data.get(c, FactorData(code=c, name=c)).dividend_yield
            portfolio_dy += (w / total_w) * dy if total_w > 0 else 0

        self.logger.info(f"组合加权股息率={portfolio_dy:.2%}")
        today = datetime.now().date()

        th1 = dy_risk.get("portfolio_below_threshold_1", 0.035)
        days1 = dy_risk.get("portfolio_consecutive_days_1", 15)
        reduce1 = dy_risk.get("portfolio_reduce_pct_1", 0.50)
        if portfolio_dy < th1:
            self.state["portfolio_dy_low_days"] = self.state.get("portfolio_dy_low_days", 0) + 1
            if self.state["portfolio_dy_low_days"] >= days1:
                for c in equity_codes:
                    if not any(s.code == c and s.signal_type == "clear" for s in signals):
                        signals.append(RiskSignal(code=c, signal_type="reduce", reason=f"组合DY<{th1:.1%}连续{days1}天,减仓{reduce1:.0%}", severity=4))
                self.logger.warning(f"组合股息率风控: 减仓{reduce1:.0%}")
        else:
            self.state["portfolio_dy_low_days"] = 0

        th2 = dy_risk.get("portfolio_below_threshold_2", 0.025)
        reduce2 = dy_risk.get("portfolio_reduce_pct_2", 1.00)
        if portfolio_dy < th2:
            for c in equity_codes:
                signals.append(RiskSignal(code=c, signal_type="clear", reason=f"组合DY<{th2:.1%},立即清仓", severity=5))
            self.logger.warning(f"组合股息率紧急风控: 立即清仓")

    # -------------------------------------------------
    # 2.5 DDCA被动补仓
    # -------------------------------------------------
    def check_ddca(self) -> List[TradeSignal]:
        self.logger.info("===== 开始DDCA被动补仓检查 =====")
        signals = []
        ddca = self.config.get("ddca", {})
        dy_trigger = ddca.get("dividend_yield_trigger", 0.055)
        drop_trigger = ddca.get("monthly_drop_trigger", 0.03)
        max_add = ddca.get("max_add_pct_per_trade", 0.10)
        total = self.config.get("total_capital", 405000)

        for h in self.holdings:
            if h.type == "cash":
                continue
            fd = self.factor_data.get(h.code)
            if fd is None:
                continue
            if fd.dividend_yield >= dy_trigger:
                add_amount = min(max_add * total, total * 0.10)
                signals.append(TradeSignal(
                    code=h.code, name=h.name, action="ddca_add",
                    reason=f"DY={fd.dividend_yield:.2%} >= {dy_trigger:.1%}，触发被动补仓",
                    suggested_amount=add_amount
                ))
                self.logger.info(f"[{h.code}] DDCA补仓(高股息): {add_amount:.0f}元")
                continue

            drop = self._calc_monthly_drop(h.code)
            if drop <= -drop_trigger:
                add_amount = min(max_add * total, total * 0.10)
                signals.append(TradeSignal(
                    code=h.code, name=h.name, action="ddca_add",
                    reason=f"月跌幅={drop:.2%} >= {drop_trigger:.1%}，触发被动补仓",
                    suggested_amount=add_amount
                ))
                self.logger.info(f"[{h.code}] DDCA补仓(月跌): {add_amount:.0f}元")
        self.logger.info(f"===== DDCA检查完成，发现{len(signals)}个信号 =====")
        return signals

    def _calc_monthly_drop(self, code: str) -> float:
        try:
            fd = self.factor_data.get(code)
            if fd is None:
                return 0.0
            if AKSHARE_AVAILABLE:
                end = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
                h = self.holdings_dict().get(code)
                if h and h.type == "stock":
                    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
                else:
                    df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
                if df is not None and len(df) >= 20:
                    df["日期"] = pd.to_datetime(df["日期"])
                    month_ago = datetime.now() - timedelta(days=30)
                    dfm = df[df["日期"] >= month_ago]
                    if len(dfm) >= 2:
                        return float(dfm["收盘"].iloc[-1] / dfm["收盘"].iloc[0] - 1)
        except Exception:
            pass
        return 0.0

    def holdings_dict(self) -> Dict[str, HoldingConfig]:
        return {h.code: h for h in self.holdings}

    # -------------------------------------------------
    # 2.6 混合信号分级调仓判断（v8.1 核心改进）
    # -------------------------------------------------
    def _update_valuation_history(self):
        """每日记录组合估值指标，用于L2触发"""
        equity_codes = [h.code for h in self.holdings if h.type != "cash"]
        total_w = sum(self.state["current_weights"].get(c, 0) for c in equity_codes)
        if total_w <= 0:
            return
        portfolio_pe = 0.0
        portfolio_dy = 0.0
        for c in equity_codes:
            w = self.state["current_weights"].get(c, 0)
            fd = self.factor_data.get(c)
            if fd:
                portfolio_pe += (w / total_w) * fd.pe_ttm
                portfolio_dy += (w / total_w) * fd.dividend_yield
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.state["valuation_history"].append({
            "date": today_str,
            "portfolio_pe": round(portfolio_pe, 4),
            "portfolio_dy": round(portfolio_dy, 4),
        })
        # 保留最近3年数据（约750交易日）
        max_hist = 750
        if len(self.state["valuation_history"]) > max_hist:
            self.state["valuation_history"] = self.state["valuation_history"][-max_hist:]
        self.logger.info(f"估值历史已更新: PE={portfolio_pe:.2f}, DY={portfolio_dy:.2%}")

    def _compute_portfolio_valuation_percentile(self) -> Tuple[Optional[float], Optional[float]]:
        """计算当前组合估值分位，返回 (PE分位, DY分位)"""
        hist = self.state["valuation_history"]
        rb = self.config.get("rebalance", {})
        min_days = rb.get("level2", {}).get("min_history_days", 60)
        if len(hist) < min_days:
            self.logger.info(f"估值历史不足{min_days}天，跳过L2分位计算")
            return None, None
        current = hist[-1]
        pe_values = [h["portfolio_pe"] for h in hist[:-1]]  # 排除当天
        dy_values = [h["portfolio_dy"] for h in hist[:-1]]
        current_pe = current["portfolio_pe"]
        current_dy = current["portfolio_dy"]
        pe_pct = sum(1 for v in pe_values if v <= current_pe) / len(pe_values) * 100 if pe_values else 50
        dy_pct = sum(1 for v in dy_values if v <= current_dy) / len(dy_values) * 100 if dy_values else 50
        self.logger.info(f"组合估值分位: PE分位={pe_pct:.1f}%, DY分位={dy_pct:.1f}%")
        return pe_pct, dy_pct

    def _check_level1_trigger(self, comprehensive: bool = False) -> List[TradeSignal]:
        """一级触发：权重偏离（5/25规则）+ 连续3日确认 + 7日冷却期"""
        signals = []
        rb = self.config.get("rebalance", {})
        l1 = rb.get("level1", {})
        abs_tol = l1.get("absolute_pct", 0.05)
        rel_tol = l1.get("relative_pct", 0.25)
        consecutive_th = l1.get("consecutive_days", 3)
        cooldown = l1.get("cooldown_days", 7)
        total = self.config.get("total_capital", 405000)
        today = datetime.now().date()
        today_str = today.strftime("%Y-%m-%d")

        for h in self.holdings:
            if h.code == "CASH":
                continue
            # 检查冷却期
            cooldown_until = self.state["l1_cooldown_until"].get(h.code)
            if cooldown_until:
                cdu = datetime.strptime(cooldown_until, "%Y-%m-%d").date() if isinstance(cooldown_until, str) else cooldown_until
                if today < cdu:
                    continue
            # 检查观察期
            obs = self.state["observation_until"].get(h.code)
            if obs:
                obs_date = datetime.strptime(obs, "%Y-%m-%d").date() if isinstance(obs, str) else obs
                if today < obs_date:
                    continue
            # 已清仓且评分低的不触发买入
            current_w = self.state["current_weights"].get(h.code, h.target_weight)
            if current_w <= 0 and h.target_weight > 0:
                sr = self.score_results.get(h.code)
                if sr and sr.total_score < 30:
                    continue

            target_w = h.target_weight
            diff = abs(current_w - target_w)
            rel_diff = diff / target_w if target_w > 0 else 0
            threshold = min(abs_tol, target_w * rel_tol)

            streak_key = h.code
            if diff > threshold:
                self.state["deviation_streaks"][streak_key] = self.state["deviation_streaks"].get(streak_key, 0) + 1
                self.logger.info(f"[{h.code}] 权重偏离: {diff:.2%} > {threshold:.2%}, 连续{self.state['deviation_streaks'][streak_key]}天")
                if self.state["deviation_streaks"][streak_key] >= consecutive_th:
                    if current_w < target_w:
                        action = "buy"
                        amount = (target_w - current_w) * total
                    else:
                        action = "sell"
                        amount = (current_w - target_w) * total
                    signals.append(TradeSignal(
                        code=h.code, name=h.name, action=action,
                        reason=f"L1-权重偏离连续{consecutive_th}天: {diff:.2%} > {threshold:.2%}",
                        suggested_amount=amount
                    ))
                    # 设置冷却期
                    cooldown_until = today + timedelta(days=cooldown)
                    self.state["l1_cooldown_until"][h.code] = cooldown_until.strftime("%Y-%m-%d")
                    self.state["deviation_streaks"][streak_key] = 0
                    self.logger.info(f"[{h.code}] L1触发{action}, 冷却期至{cooldown_until}")
            else:
                if self.state["deviation_streaks"].get(streak_key, 0) > 0:
                    self.logger.info(f"[{h.code}] 权重回归正常，重置偏离计数")
                self.state["deviation_streaks"][streak_key] = 0
        return signals

    def _check_level2_trigger(self) -> List[TradeSignal]:
        """二级触发：估值分位极端 + 连续5日确认 → 全组合再平衡"""
        signals = []
        rb = self.config.get("rebalance", {})
        l2 = rb.get("level2", {})
        over_pct = l2.get("overvalued_percentile", 85)
        under_pct = l2.get("undervalued_percentile", 15)
        consecutive_th = l2.get("consecutive_days", 5)
        total = self.config.get("total_capital", 405000)
        today = datetime.now().date()

        pe_pct, dy_pct = self._compute_portfolio_valuation_percentile()
        if pe_pct is None or dy_pct is None:
            return signals

        # 判断当前估值状态
        current_direction = None
        if pe_pct > over_pct or dy_pct < (100 - over_pct):
            current_direction = "overvalued"
        elif pe_pct < under_pct or dy_pct > (100 - under_pct):
            current_direction = "undervalued"

        if current_direction:
            if self.state["level2_direction"] == current_direction:
                self.state["level2_streak"] += 1
            else:
                self.state["level2_direction"] = current_direction
                self.state["level2_streak"] = 1
            self.logger.info(f"L2方向={current_direction}, 连续{self.state['level2_streak']}天")
        else:
            if self.state["level2_streak"] > 0:
                self.logger.info("L2条件消失，重置计数")
            self.state["level2_streak"] = 0
            self.state["level2_direction"] = None

        if self.state["level2_streak"] >= consecutive_th:
            reason = f"L2-估值分位{current_direction}连续{consecutive_th}天 (PE分位={pe_pct:.1f}%, DY分位={dy_pct:.1f}%)"
            self.logger.warning(f"!!! {reason}，触发全组合再平衡")
            for h in self.holdings:
                if h.code == "CASH":
                    continue
                current_w = self.state["current_weights"].get(h.code, h.target_weight)
                if abs(current_w - h.target_weight) > 0.001:
                    diff = h.target_weight - current_w
                    action = "buy" if diff > 0 else "sell"
                    signals.append(TradeSignal(
                        code=h.code, name=h.name, action=action,
                        reason=reason,
                        suggested_amount=abs(diff) * total
                    ))
            # 触发后重置
            self.state["level2_streak"] = 0
        return signals

    def _check_time_backup_trigger(self) -> List[TradeSignal]:
        """时间保底：每年1月/7月强制全面检查"""
        signals = []
        rb = self.config.get("rebalance", {})
        months = rb.get("time_backup_months", [1, 7])
        day = rb.get("time_backup_day", 1)
        today = datetime.now()
        total = self.config.get("total_capital", 405000)

        if today.month in months and today.day == day:
            self.logger.info("=== 时间保底触发：半年度强制全面再平衡 ===")
            for h in self.holdings:
                if h.code == "CASH":
                    continue
                current_w = self.state["current_weights"].get(h.code, h.target_weight)
                if abs(current_w - h.target_weight) > 0.001:
                    diff = h.target_weight - current_w
                    action = "buy" if diff > 0 else "sell"
                    signals.append(TradeSignal(
                        code=h.code, name=h.name, action=action,
                        reason="时间保底-半年度强制再平衡",
                        suggested_amount=abs(diff) * total
                    ))
        return signals

    def _generate_first_build_signals(self) -> List[TradeSignal]:
        """首次运行：生成第1批建仓信号（30%仓位）"""
        signals = []
        total = self.config.get("total_capital", 405000)
        build_cfg = self.config.get("build_plan", {})
        batches = build_cfg.get("batches", [])
        rules = build_cfg.get("rules", {})
        min_score = rules.get("min_score_threshold", 50)

        if not batches:
            self.logger.warning("未配置build_plan.batches，跳过建仓")
            return signals

        batch1 = batches[0]  # 第1批：30%，立即执行
        batch1_pct = batch1.get("weight_pct", 0.30)

        self.logger.info(f"===== 首次运行：生成第1批建仓信号（{batch1_pct:.0%}仓位）=====")

        for h in self.holdings:
            if h.type == "cash":
                continue
            # 已触发风控清仓的标的不建仓
            if h.code in [s.code for s in self.risk_signals if s.signal_type == "clear"]:
                self.logger.info(f"[{h.code}] 已触发风控清仓，建仓跳过")
                continue
            sr = self.score_results.get(h.code)
            if not sr:
                continue
            # 评分不够的不建仓
            if sr.total_score < min_score:
                self.logger.info(f"[{h.code}] 评分{sr.total_score:.1f}<{min_score}，建仓跳过")
                continue

            build_amount = h.target_amount * batch1_pct
            shares = int(build_amount / h.price / h.min_lots) * h.min_lots if h.price > 0 else 0
            actual_amount = shares * h.price if shares > 0 else 0

            if actual_amount > 0:
                signals.append(TradeSignal(
                    code=h.code, name=h.name, action="buy",
                    reason=f"第1批建仓({batch1_pct:.0%})-评分{sr.total_score:.1f}",
                    suggested_amount=actual_amount
                ))
                self.logger.info(f"[{h.code}] 第1批: {shares}股={actual_amount:,.0f}元")

        # 初始化建仓状态
        self.state["build_state"] = {
            "current_batch": 1,
            "build_start_date": datetime.now().strftime("%Y-%m-%d"),
            "build_day_counter": 0,
            "first_batch_prices": {},  # code -> 首批买入价格
            "completed_batches": {1: True},
            "paused_codes": {},        # code -> "reason"
        }
        # 记录首仓成本
        for ts in signals:
            fd = self.factor_data.get(ts.code)
            if fd:
                self.state["build_state"]["first_batch_prices"][ts.code] = fd.price

        self.logger.info(f"===== 第1批建仓信号完成，共{len(signals)}个，后续批次将自动触发 =====")
        return signals

    def _check_build_progression(self) -> List[TradeSignal]:
        """建仓期间：检查是否需要触发下一批次"""
        signals = []
        build_cfg = self.config.get("build_plan", {})
        batches = build_cfg.get("batches", [])
        rules = build_cfg.get("rules", {})
        min_score = rules.get("min_score_threshold", 50)
        pause_score = rules.get("pause_score_threshold", 35)

        build_state = self.state.get("build_state")
        if not build_state:
            return signals

        current_batch = build_state.get("current_batch", 1)
        build_state["build_day_counter"] = build_state.get("build_day_counter", 0) + 1
        day_counter = build_state["build_day_counter"]

        self.logger.info(f"建仓进度: 第{current_batch}批，累计{day_counter}交易日")

        # 遍历未完成的批次，检查是否满足触发条件
        for batch_cfg in batches:
            batch_num = batch_cfg.get("batch", 0)
            if batch_num <= current_batch:
                continue
            if build_state.get("completed_batches", {}).get(batch_num, False):
                continue

            # 检查触发条件
            trigger = batch_cfg.get("trigger", "time_or_drop")
            batch_pct = batch_cfg.get("weight_pct", 0)
            time_deadline = batch_cfg.get("time_deadline_days", 10)
            price_drop = batch_cfg.get("price_drop_pct", 0.05)
            description = batch_cfg.get("description", "")

            triggered = False
            trigger_reason = ""

            if trigger == "immediate":
                triggered = True
                trigger_reason = "立即执行"
            elif trigger == "time_or_drop":
                # 时间触发
                if day_counter >= time_deadline:
                    triggered = True
                    trigger_reason = f"到达{time_deadline}日时间节点"
                # 价格下跌触发
                elif price_drop > 0:
                    first_prices = build_state.get("first_batch_prices", {})
                    for h in self.holdings:
                        if h.type == "cash" or h.code in [s.code for s in self.risk_signals if s.signal_type == "clear"]:
                            continue
                        fd = self.factor_data.get(h.code)
                        first_price = first_prices.get(h.code)
                        if fd and first_price and first_price > 0:
                            drop = (first_price - fd.price) / first_price
                            if drop >= price_drop:
                                triggered = True
                                trigger_reason = f"较首仓成本下跌{drop:.1%}"
                                break

            if triggered:
                self.logger.info(f"=== 第{batch_num}批建仓触发: {trigger_reason} ({description}) ===")
                for h in self.holdings:
                    if h.type == "cash":
                        continue
                    if h.code in [s.code for s in self.risk_signals if s.signal_type == "clear"]:
                        continue
                    if build_state.get("paused_codes", {}).get(h.code):
                        continue
                    sr = self.score_results.get(h.code)
                    if not sr:
                        continue
                    if sr.total_score < pause_score:
                        self.logger.info(f"[{h.code}] 评分{sr.total_score:.1f}<{pause_score}，暂停后续建仓")
                        if "paused_codes" not in build_state:
                            build_state["paused_codes"] = {}
                        build_state["paused_codes"][h.code] = f"评分{sr.total_score:.1f}<{pause_score}"
                        continue

                    # 计算该批次应买入金额
                    prev_pct = sum(
                        b.get("weight_pct", 0) for b in batches
                        if b.get("batch", 0) < batch_num
                    )
                    this_batch_pct = batch_pct
                    build_amount = h.target_amount * this_batch_pct
                    shares = int(build_amount / h.price / h.min_lots) * h.min_lots if h.price > 0 else 0
                    actual_amount = shares * h.price if shares > 0 else 0

                    if actual_amount > 0:
                        signals.append(TradeSignal(
                            code=h.code, name=h.name, action="buy",
                            reason=f"第{batch_num}批建仓({this_batch_pct:.0%})-{trigger_reason}",
                            suggested_amount=actual_amount
                        ))
                        self.logger.info(f"[{h.code}] 第{batch_num}批: {shares}股={actual_amount:,.0f}元")

                build_state["current_batch"] = batch_num
                build_state["completed_batches"][batch_num] = True

                # 检查是否全部批次完成
                all_done = all(
                    build_state.get("completed_batches", {}).get(b.get("batch"), False)
                    for b in batches
                )
                if all_done:
                    self.state["first_build_completed"] = True
                    self.state["trading_day_counter"] = day_counter
                    self.logger.info("===== 建仓全部完成（4/4批），进入持有期 =====")
                break  # 每次只触发一个批次

        return signals

    def check_rebalance(self) -> List[TradeSignal]:
        """混合信号分级调仓主入口"""
        self.logger.info("===== 开始混合信号分级调仓判断 =====")
        signals = []
        rb = self.config.get("rebalance", {})
        today = datetime.now()
        build_months = rb.get("build_period_months", 3)
        in_build = (today - HOLDING_START_DATE).days < build_months * 30

        # 每日更新估值历史
        self._update_valuation_history()

        if in_build:
            interval = rb.get("build_period_check_interval_days", 14)
            self.logger.info(f"当前处于建仓期（每{interval}天检查）")
            tol_signals = self.check_tolerance()
            signals.extend(tol_signals)
        else:
            # 持有期：混合信号方案
            check_interval = rb.get("holding_check_interval_days", 10)
            self.state["trading_day_counter"] = self.state.get("trading_day_counter", 0) + 1
            counter = self.state["trading_day_counter"]

            # 判断是否到达综合检查日（每10交易日 或 时间保底日）
            time_backup_signals = self._check_time_backup_trigger()
            is_comprehensive_day = (counter % check_interval == 0) or len(time_backup_signals) > 0

            if time_backup_signals:
                signals.extend(time_backup_signals)
                self.logger.info(f"时间保底触发，共{len(time_backup_signals)}个信号")

            if is_comprehensive_day:
                self.logger.info(f"综合检查日（累计{counter}交易日，每{check_interval}日检查）")
                self.state["last_comprehensive_check"] = today.strftime("%Y-%m-%d")

                # L1: 权重偏离（单标的）
                l1_signals = self._check_level1_trigger(comprehensive=True)
                signals.extend(l1_signals)

                # L2: 估值分位（全组合）
                l2_signals = self._check_level2_trigger()
                signals.extend(l2_signals)

                # L3: 基本面红线已在check_risk_control中处理，此处仅记录
                if self.risk_signals:
                    l3_count = sum(1 for s in self.risk_signals if s.signal_type == "clear")
                    if l3_count > 0:
                        self.logger.info(f"L3-基本面红线触发{l3_count}个清仓信号，已在前序风控阶段处理")

                self.logger.info(f"综合检查完成: L1={len(l1_signals)}, L2={len(l2_signals)}, L3已处理")
            else:
                self.logger.info(f"非综合检查日（距下次检查还有{check_interval - counter % check_interval}交易日），仅更新估值历史")

        self.logger.info(f"===== 调仓判断完成，共{len(signals)}个信号 =====")
        return signals

    # -------------------------------------------------
    # 2.7 权重重分配
    # -------------------------------------------------
    def rebalance_weights(self):
        self.logger.info("===== 开始权重重分配 =====")
        cleared = [s.code for s in self.risk_signals if s.signal_type == "clear"]
        if not cleared:
            self.logger.info("无清仓标的，无需重分配")
            return

        healthy = [h for h in self.holdings if h.code not in cleared and h.type != "cash"]
        if not healthy:
            self.logger.warning("所有权益标的均触发清仓，全部转为现金")
            for h in self.holdings:
                self.state["current_weights"][h.code] = 0.0 if h.type != "cash" else 1.0
            return

        freed_weight = sum(self.state["current_weights"].get(c, 0) for c in cleared)
        self.logger.info(f"清仓标的释放权重: {freed_weight:.2%}")

        total_healthy_weight = sum(h.target_weight for h in healthy)
        single_max = self.config.get("risk_control", {}).get("single_max_weight", 0.25)

        for h in healthy:
            alloc = freed_weight * (h.target_weight / total_healthy_weight) if total_healthy_weight > 0 else 0
            new_w = self.state["current_weights"].get(h.code, h.target_weight) + alloc
            new_w = min(new_w, single_max)
            self.state["current_weights"][h.code] = new_w
            self.logger.info(f"[{h.code}] 权重调整: {self.state['current_weights'].get(h.code, 0):.2%} -> {new_w:.2%}")

        for c in cleared:
            self.state["current_weights"][c] = 0.0

        cash_w = 1.0 - sum(self.state["current_weights"].get(h.code, 0) for h in self.holdings if h.type != "cash")
        cash_h = next((h for h in self.holdings if h.type == "cash"), None)
        if cash_h:
            self.state["current_weights"][cash_h.code] = max(0.0, cash_w)
        self.logger.info("===== 权重重分配完成 =====")

    # -------------------------------------------------
    # 2.8 现金管理（ERP动态）
    # -------------------------------------------------
    def adjust_cash_by_erp(self):
        self.logger.info("===== 开始ERP动态现金管理 =====")
        erp = self.fetch_erp()
        erp_rules = self.config.get("cash_management", {}).get("erp_to_cash", [])
        erp_rules = sorted(erp_rules, key=lambda x: x["min_erp"], reverse=True)
        target_cash_weight = 0.30
        erp_pct = erp * 100.0  # 转为百分比数字与配置比较
        for rule in erp_rules:
            if erp_pct >= rule["min_erp"]:
                target_cash_weight = rule["cash_weight"]
                break
        self.logger.info(f"当前ERP={erp*100:.2f}%, 目标现金比例={target_cash_weight:.1%}")

        equity_codes = [h.code for h in self.holdings if h.type != "cash"]
        current_equity_total = sum(self.state["current_weights"].get(c, 0) for c in equity_codes)
        target_equity_total = 1.0 - target_cash_weight

        if current_equity_total > 0 and target_equity_total >= 0:
            scale = target_equity_total / current_equity_total
            for c in equity_codes:
                self.state["current_weights"][c] *= scale
                self.logger.info(f"[{c}] ERP权益权重缩放: {scale:.2%}")

        cash_h = next((h for h in self.holdings if h.type == "cash"), None)
        if cash_h:
            self.state["current_weights"][cash_h.code] = target_cash_weight
        self.logger.info("===== ERP现金管理完成 =====")

    # -------------------------------------------------
    # 2.9 报告生成
    # -------------------------------------------------
    def generate_report(self) -> str:
        today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = []
        lines.append("=" * 40)
        lines.append(f"v8.2红利策略监测日报 | {today_str}")
        lines.append("=" * 40)
        lines.append("")

        lines.append("【组合概览】")
        total = self.config.get("total_capital", 405000)
        lines.append(f"总资金: {total:,.0f}元")
        cash_w = self.state["current_weights"].get("CASH", 0.05)
        lines.append(f"当前现金比例: {cash_w:.1%}")
        # 显示调仓状态
        rb = self.config.get("rebalance", {})
        counter = self.state.get("trading_day_counter", 0)
        interval = rb.get("holding_check_interval_days", 10)
        last_check = self.state.get("last_comprehensive_check", "无")
        # 首次运行标记
        if self.is_first_run and not self.state.get("first_build_completed", False):
            lines.append("⚡ 【首次运行】将生成第1批建仓信号（30%仓位），后续批次自动触发")
        elif not self.state.get("first_build_completed", False) and self.state.get("build_state"):
            bs = self.state["build_state"]
            cb = bs.get("current_batch", 1)
            dc = bs.get("build_day_counter", 0)
            paused = bs.get("paused_codes", {})
            pause_info = f" | ⏸️暂停建仓: {', '.join(paused.keys())}" if paused else ""
            lines.append(f"📦 【建仓中】第{cb}/4批 | 累计{dc}交易日{pause_info}")
        else:
            lines.append(f"调仓模式: 混合信号分级 | 累计{counter}交易日 | 上次综合检查: {last_check} | 距下次检查: {interval - counter % interval}日")
        lines.append("")

        lines.append("【标的评分与仓位】")
        for code in sorted(self.score_results.keys()):
            sr = self.score_results[code]
            fd = self.factor_data.get(code)
            current_w = self.state["current_weights"].get(code, 0)
            target_w = sr.target_position_pct
            days = self.state["holding_days"].get(code, 0)
            tax_hint = "(已满1年免税)" if days > 365 else f"(持股{days}天)"
            # 红绿灯图标：评分>=60绿灯，40-59黄灯，<40红灯
            if sr.total_score >= 60:
                light = "🟢"
            elif sr.total_score >= 40:
                light = "🟡"
            else:
                light = "🔴"
            lines.append(f"  {light} {code} {sr.name}: 评分={sr.total_score:.1f} 目标仓位={target_w:.0%} 当前权重={current_w:.1%} DY={fd.dividend_yield:.2%} {tax_hint}")
        lines.append("")

        lines.append("【风控信号】")
        if self.risk_signals:
            for s in self.risk_signals:
                icon = "🚨" if s.signal_type == "clear" else "⚠️"
                lines.append(f"  {icon} [{'清仓' if s.signal_type=='clear' else '减仓' if s.signal_type=='reduce' else s.signal_type}] {s.code}: {s.reason}")
        else:
            lines.append("  ✅ 无风控信号")
        lines.append("")

        lines.append("【交易信号】")
        all_signals = self.trade_signals
        if all_signals:
            for ts in all_signals:
                icon = "🟢" if ts.action == "buy" else "🔴" if ts.action == "sell" or ts.action == "clear" else "🟡"
                lines.append(f"  {icon} [{ts.action.upper()}] {ts.code} {ts.name}: {ts.reason}, 建议金额={ts.suggested_amount:,.0f}元")
        else:
            lines.append("  ⏸️ 无交易信号")
        lines.append("")

        lines.append("【分红与税务】")
        if self.is_first_run:
            lines.append("  🆕 首次建仓中，持股天数为0，分红待建仓完成后开始计算")
        else:
            for h in self.holdings:
                if h.type == "cash":
                    continue
                days = self.state["holding_days"].get(h.code, 0)
                if days > 365:
                    lines.append(f"  {h.code} {h.name}: 持股{days}天，已满1年，分红免税")
                elif days > 0:
                    lines.append(f"  {h.code} {h.name}: 持股{days}天，距免税还有{365-days}天")
                else:
                    lines.append(f"  {h.code} {h.name}: 尚未建仓")
        lines.append(f"  现金池余额: {self.state['cash_pool']:,.0f}元（建仓完成后按ERP再投资）")
        lines.append("")

        lines.append("=" * 40)
        lines.append("报告生成完毕")
        return "\n".join(lines)

    # -------------------------------------------------
    # 2.10 企业微信推送
    # -------------------------------------------------
    def push_wechat(self, content: str):
        env_name = self.config.get("notification", {}).get("wechat_webhook_env", "WECHAT_WEBHOOK_URL")
        webhook_url = os.environ.get(env_name)
        if not webhook_url:
            self.logger.warning(f"未设置环境变量 {env_name}，跳过企业微信推送")
            return

        chunks = [content[i:i + 4000] for i in range(0, len(content), 4000)]
        for idx, chunk in enumerate(chunks):
            payload = {"msgtype": "text", "text": {"content": chunk}}
            try:
                resp = requests.post(webhook_url, json=payload, timeout=15)
                self.logger.info(f"企业微信推送第{idx + 1}/{len(chunks)}段: HTTP{resp.status_code}")
            except Exception as e:
                self.logger.error(f"企业微信推送失败: {e}")

    # -------------------------------------------------
    # 2.11 主流程
    # -------------------------------------------------
    def run(self):
        self.logger.info("========================================")
        self.logger.info("v8红利策略监测启动")
        self.logger.info("========================================")
        try:
            self.fetch_data()
        except Exception as e:
            self.logger.error(f"数据获取阶段异常: {e}\n{traceback.format_exc()}")
            return

        try:
            self.compute_factors_and_score()
        except Exception as e:
            self.logger.error(f"评分计算阶段异常: {e}\n{traceback.format_exc()}")

        try:
            self.check_risk_control()
            self.rebalance_weights()
        except Exception as e:
            self.logger.error(f"风控检查异常: {e}\n{traceback.format_exc()}")

        try:
            self.adjust_cash_by_erp()
        except Exception as e:
            self.logger.error(f"ERP现金管理异常: {e}\n{traceback.format_exc()}")

        try:
            if self.is_first_run and not self.state.get("first_build_completed", False):
                # 首次运行：生成第1批建仓信号
                build_signals = self._generate_first_build_signals()
                self.trade_signals.extend(build_signals)
            elif not self.state.get("first_build_completed", False) and self.state.get("build_state"):
                # 建仓中：检查是否需要触发下一批
                build_signals = self._check_build_progression()
                self.trade_signals.extend(build_signals)
            else:
                # 持有期：正常调仓逻辑
                reb_signals = self.check_rebalance()
                ddca_signals = self.check_ddca()
                self.trade_signals = reb_signals + ddca_signals
        except Exception as e:
            self.logger.error(f"信号生成异常: {e}\n{traceback.format_exc()}")

        try:
            report = self.generate_report()
            self.logger.info("\n" + report)
            self.push_wechat(report)
        except Exception as e:
            self.logger.error(f"报告生成/推送异常: {e}\n{traceback.format_exc()}")

        # 保存持久化状态
        self._save_persistent_state()

        self.logger.info("========================================")
        self.logger.info("v8红利策略监测结束")
        self.logger.info("========================================")


# ============================================
# 3. 入口
# ============================================
def main():
    config_path = os.environ.get("DIVIDEND_CONFIG", "config.yaml")
    monitor = DividendMonitor(config_path)
    monitor.run()


if __name__ == "__main__":
    main()
