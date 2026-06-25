from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.auth.security import hash_password, verify_password, generate_token
from app.models import user as user_model

router = APIRouter()


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    email_to: EmailStr | None = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(body: RegisterBody):
    if user_model.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="email already registered")
    token = generate_token()
    email_to = body.email_to or body.email
    user_model.create_user(
        body.email, hash_password(body.password), email_to, token
    )
    return {"token": token}


@router.post("/login")
def login(body: LoginBody):
    u = user_model.get_user_by_email(body.email)
    if not u or not verify_password(body.password, u["password"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = generate_token()
    user_model.set_user_token(u["id"], token)
    return {"token": token}
