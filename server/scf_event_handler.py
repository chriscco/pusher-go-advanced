"""SCF Event 函数入口：由每日 Timer 触发，跑一次日报流水线。

HTTP 函数不能挂 timer（且 API 网关已停售），故每日流水线用独立的
Event 函数 + Timer 触发器实现。Handler 配置为 scf_event_handler.main_handler。
"""
import os
import sys

# SCF 只有 /tmp 可写。把 HOME 指到 /tmp，让走 HOME/缓存目录的库（yfinance 等）能落盘。
os.environ.setdefault("HOME", "/tmp")

# Layer 依赖装在 /opt/python；Event 函数不跑 scf_bootstrap，且 SCF 禁止设置
# PYTHONPATH 环境变量，故在此手动把层目录加入 sys.path（须在 import app 之前）。
for _p in ("/opt/python", "/opt"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.models import job as job_model
from app.pipeline.pipeline import run_job


def main_handler(event, context=None):
    # 定时触发器把 CustomArgument 放在 event["Message"]
    expected = os.environ.get("TIMER_SECRET")
    message = event.get("Message") if isinstance(event, dict) else None
    if expected and message != expected:
        return {"ok": False, "error": "invalid timer secret"}

    job_id = job_model.create_job("pipeline", user_id=None)
    run_job(job_id)
    row = job_model.get_job(job_id)
    return {"ok": True, "job_id": job_id, "status": row["status"] if row else None}
