import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from app.database import get_conn
from app.models.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.security import hash_password, issue_token, require_auth, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest):
    user_id = str(uuid.uuid4())
    password_hash = hash_password(body.password)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
            if cur.fetchone() is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
            try:
                cur.execute(
                    "INSERT INTO users (id, email, name, password_hash) VALUES (%s, %s, %s, %s)",
                    (user_id, body.email, body.name, password_hash),
                )
                conn.commit()
            except psycopg.errors.UniqueViolation:
                # Two concurrent registrations for the same email raced past
                # the SELECT check above; the UNIQUE constraint is the real
                # guard — surface it as a clean 409, not a raw 500.
                conn.rollback()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    token = issue_token(user_id, body.email)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, email, password_hash FROM users WHERE email = %s", (body.email,))
            row = cur.fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token = issue_token(row["id"], row["email"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(auth: dict = Depends(require_auth)):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, email, name, created_at FROM users WHERE id = %s", (auth["user_id"],))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(**row)
