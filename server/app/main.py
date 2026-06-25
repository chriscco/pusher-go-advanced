from fastapi import FastAPI
from app.api import auth, portfolio, report

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(report.router)
