from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from app.deps import get_current_user
from app.models import report as report_model

router = APIRouter()


def _serialize(row):
    rd = row["report_date"]
    return {
        "report_date": rd.strftime("%Y-%m-%d") if hasattr(rd, "strftime") else str(rd),
        "content": row["content"],
        "news_summary": row["news_summary"],
        "stock_summary": row["stock_summary"],
        "personal_analysis": row["personal_analysis"],
    }


@router.get("/report/list")
def list_reports(user=Depends(get_current_user)):
    return {"dates": report_model.list_report_dates(user["id"])}


@router.get("/report/today")
def report_today(user=Depends(get_current_user)):
    row = report_model.get_today_report(user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="no report today")
    return _serialize(row)


@router.get("/report/{date}")
def report_by_date(date: str, user=Depends(get_current_user)):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    row = report_model.get_report(user["id"], date)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return _serialize(row)
