from fastapi import Header, HTTPException
from app.models import user as user_model


def get_current_user(authorization: str = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer "):]
    u = user_model.get_user_by_token(token)
    if not u:
        raise HTTPException(status_code=401, detail="invalid token")
    return u
