from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from app.deps import get_current_user
from app.models import job as job_model
from app.pipeline.pipeline import run_job

router = APIRouter()


@router.post("/trigger-report", status_code=202)
def trigger(background: BackgroundTasks, user=Depends(get_current_user)):
    job_id = job_model.create_job("manual_report", user_id=user["id"])
    background.add_task(run_job, job_id)
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def job_status(job_id: str, user=Depends(get_current_user)):
    row = job_model.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    rd = row["report_date"]
    return {
        "id": row["id"],
        "status": row["status"],
        "report_date": rd.strftime("%Y-%m-%d") if rd else None,
        "error": row["error"],
    }
