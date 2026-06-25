from fastapi import FastAPI
from app.api import auth

app = FastAPI(title="pusher-go-advanced")
app.include_router(auth.router)
