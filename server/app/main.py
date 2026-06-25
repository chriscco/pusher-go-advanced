from fastapi import FastAPI
from app.api import auth, portfolio, report, job, timer, health

app = FastAPI(title="pusher-go-advanced")
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(report.router)
app.include_router(job.router)
app.include_router(timer.router)
