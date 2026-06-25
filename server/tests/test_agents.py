from app.data.models import IndexQuote, SectorInfo, NewsItem
from app.agents import agents


def make_chat(capture):
    def chat_fn(messages, model):
        capture["prompt"] = messages[-1]["content"]
        capture["model"] = model
        return "AGENT_OUTPUT"
    return chat_fn


def test_market_analyst_includes_data():
    cap = {}
    out = agents.run_market_analyst(
        [IndexQuote("上证指数", "000001", 3000.0, 1.2)],
        [SectorInfo("半导体", 2.5, 1e8)],
        make_chat(cap), "deepseek-chat",
    )
    assert out == "AGENT_OUTPUT"
    assert "上证指数" in cap["prompt"]
    assert "半导体" in cap["prompt"]
    assert cap["model"] == "deepseek-chat"


def test_news_editor_includes_titles():
    cap = {}
    agents.run_news_editor(
        [NewsItem("重大新闻", "http://u", "src", None)], make_chat(cap), "m"
    )
    assert "重大新闻" in cap["prompt"]


def test_advisor_includes_holdings():
    cap = {}
    agents.run_advisor("u@x.com", ["600519 贵州茅台 +1.2%"], make_chat(cap), "m")
    assert "600519" in cap["prompt"]


def test_reviewer_combines_sections():
    cap = {}
    out = agents.run_reviewer(
        "今日大纲",
        {"market": "M", "news": "N", "sector": "S", "advisor": "A"},
        make_chat(cap), "m",
    )
    assert out == "AGENT_OUTPUT"
    for token in ("今日大纲", "M", "N", "S", "A"):
        assert token in cap["prompt"]
