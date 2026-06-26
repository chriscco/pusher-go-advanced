import sys

from app.config import load_settings
from app.models import user as user_model
from app.models import portfolio as pf_model
from app.models import report as report_model
from app.models import job as job_model
from app.models.report import beijing_today
from app.agents import agents
from app.agents.llm import chat as default_chat
from app.pipeline.email import send_report_email


def _holdings_lines(provider, holdings):
    lines = []
    for h in holdings:
        q = provider.get_stock_quote(h["symbol"], h["market"])
        if q.price is None:
            price = "数据暂不可用"
        elif q.change_pct is None:
            price = f"{q.price}"
        else:
            price = f"{q.price} ({q.change_pct:+.2f}%)"
        qty = "" if h["quantity"] is None else f" 持有{h['quantity']}"
        lines.append(f"{h['symbol']} {h.get('name') or ''} {price}{qty}")
    return lines


def run_pipeline(*, bundle, provider, chat_fn, email_sender, report_date) -> int:
    s = load_settings()
    planner_model = s.planner_model
    analyst_model = s.analyst_model
    reviewer_model = s.reviewer_model

    indices = bundle["indices"]
    sectors = bundle["sectors"]
    news = bundle["news"]

    overview = ", ".join(u["email"] for u in user_model.list_all_users())
    events_text = "\n".join(f"- {n.title}" for n in news)
    outline = agents.run_planner(events_text, overview, chat_fn, planner_model)

    market_section = agents.run_market_analyst(indices, sectors, chat_fn, analyst_model)
    news_section = agents.run_news_editor(news, chat_fn, analyst_model)
    sector_section = agents.run_sector_analyst(sectors, chat_fn, analyst_model)

    count = 0
    for u in user_model.list_all_users():
        try:
            holdings = pf_model.list_portfolios(u["id"])
            advisor_section = agents.run_advisor(
                u["email"], _holdings_lines(provider, holdings), chat_fn, analyst_model
            )
            html = agents.run_reviewer(
                outline,
                {
                    "market": market_section,
                    "news": news_section,
                    "sector": sector_section,
                    "advisor": advisor_section,
                },
                chat_fn, reviewer_model,
            )
            report_model.save_report(
                u["id"], report_date, html,
                news_section, market_section, advisor_section,
            )
            email_sender(u["email_to"], f"每日金融日报 {report_date}", html)
            count += 1
        except Exception:
            # 单用户失败不影响其他用户
            continue
    return count


def _safe_source(label, fn, default):
    """单个数据源失败不影响整体：记录并降级为默认值（graceful degradation）。"""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — 外部数据源各异，统一兜底
        print(f"[pipeline] 数据源 {label} 获取失败，降级为空: {e!r}", file=sys.stderr)
        return default


def _default_runner():
    from app.data.provider import MarketDataProvider
    from app.data.ak import AkSource
    from app.data.ef import EfSource
    from app.data.yf import YfSource
    from app.data import market

    provider = MarketDataProvider(AkSource(), EfSource(), YfSource())
    bundle = {
        "indices": _safe_source("indices", market.get_index_quotes, []),
        "sectors": _safe_source("sectors", market.get_sector_ranking, []),
        "news": _safe_source("news", lambda: market.fetch_news(_load_rss_sources()), []),
    }
    report_date = beijing_today()
    run_pipeline(
        bundle=bundle, provider=provider, chat_fn=default_chat,
        email_sender=send_report_email, report_date=report_date,
    )
    return report_date


def _load_rss_sources():
    from app.db import mysql
    return mysql.query(
        "SELECT name, url FROM rss_sources WHERE enabled = TRUE"
    )


def run_job(job_id, *, runner=None) -> None:
    runner = runner or _default_runner
    job_model.mark_running(job_id)
    try:
        report_date = runner()
        job_model.mark_done(job_id, report_date)
    except Exception as e:  # noqa: BLE001
        job_model.mark_failed(job_id, e)
