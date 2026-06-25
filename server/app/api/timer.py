import os
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from app.models import job as job_model
from app.pipeline.pipeline import run_job

router = APIRouter()


@router.post("/internal/timer", status_code=202)
def timer(background: BackgroundTasks, x_timer_secret: str = Header(default=None)):
    expected = os.environ.get("TIMER_SECRET")
    if not expected or x_timer_secret != expected:
        raise HTTPException(status_code=401, detail="invalid timer secret")
    job_id = job_model.create_job("pipeline", user_id=None)
    background.add_task(run_job, job_id)
    return {"job_id": job_id}


@router.post("/", status_code=202)
async def scf_timer_root(request: Request, background: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        body = {}
    expected = os.environ.get("TIMER_SECRET")
    if body.get("Type") != "Timer" or not expected or body.get("Message") != expected:
        raise HTTPException(status_code=401, detail="invalid timer event")
    job_id = job_model.create_job("pipeline", user_id=None)
    background.add_task(run_job, job_id)
    return {"job_id": job_id}
