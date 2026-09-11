from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import authenticate, issue_token, require_user, throttled

router = APIRouter(prefix="/api/auth", tags=["인증"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login", summary="로그인 (토큰 발급)")
def login(body: LoginIn):
    if throttled(body.username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "로그인 실패가 너무 많습니다. 1분 뒤에 다시 시도하세요.")
    role = authenticate(body.username, body.password)
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 맞지 않습니다.")
    token, exp = issue_token(body.username, role)
    return {"access_token": token, "token_type": "bearer",
            "username": body.username, "role": role, "expires_at": exp}


@router.get("/me", summary="지금 로그인한 계정")
def me(user: dict = Depends(require_user)):
    return {"username": user["sub"], "role": user["role"], "expires_at": user["exp"]}
