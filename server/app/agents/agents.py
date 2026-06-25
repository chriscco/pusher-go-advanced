def _ask(chat_fn, model, prompt):
    return chat_fn([{"role": "user", "content": prompt}], model)


def run_planner(events_text, portfolios_overview, chat_fn, model) -> str:
    prompt = (
        "你是金融日报主编。基于以下当日核心事件与全部用户持仓概览，"
        "用要点列出今日报告大纲，并标注每个用户的关注重点。\n\n"
        f"【核心事件】\n{events_text}\n\n【持仓概览】\n{portfolios_overview}\n"
    )
    return _ask(chat_fn, model, prompt)


def run_market_analyst(indices, sectors, chat_fn, model) -> str:
    idx = "\n".join(f"{i.name} {i.price} ({i.change_pct:+.2f}%)" for i in indices)
    sec = "\n".join(f"{s.name} ({s.change_pct:+.2f}%)" for s in sectors)
    prompt = (
        "你是市场分析师。根据大盘指数与板块数据写一段简明的市场概览。\n\n"
        f"【大盘】\n{idx}\n\n【板块】\n{sec}\n"
    )
    return _ask(chat_fn, model, prompt)


def run_news_editor(news_items, chat_fn, model) -> str:
    lines = "\n".join(f"- {n.title} ({n.source})" for n in news_items)
    prompt = (
        "你是新闻编辑。从以下新闻中精选 5-8 条最重要的，"
        "每条给一句简短点评。\n\n" + lines
    )
    return _ask(chat_fn, model, prompt)


def run_sector_analyst(sectors, chat_fn, model) -> str:
    sec = "\n".join(
        f"{s.name} ({s.change_pct:+.2f}%) 主力净流入 {s.main_inflow}" for s in sectors
    )
    prompt = "你是板块轮动分析师。根据板块涨跌与资金流向分析今日热点。\n\n" + sec
    return _ask(chat_fn, model, prompt)


def run_advisor(user_email, holdings_lines, chat_fn, model) -> str:
    holdings = "\n".join(holdings_lines) if holdings_lines else "（无持仓）"
    prompt = (
        f"你是 {user_email} 的个人投资顾问。根据其持仓及当日行情，"
        "给出个性化涨跌分析与简要建议。\n\n【持仓与行情】\n" + holdings
    )
    return _ask(chat_fn, model, prompt)


def run_reviewer(outline, sections, chat_fn, model) -> str:
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    prompt = (
        "你是主编。把以下各部分整合成一篇连贯的 HTML 日报，"
        "检查数据一致性并优化文风，直接输出完整 HTML。\n\n"
        f"【大纲】\n{outline}\n\n【素材】\n{body}\n"
    )
    return _ask(chat_fn, model, prompt)
