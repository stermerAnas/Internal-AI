from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from idemkit import IdempotencyMiddleware, InMemoryBackend
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from internal_ai.app.authentication import (
    create_refresh_token,
    create_token,
    get_current_user,
    hash_password,
    hash_refresh_token,
    verify_hashed_password,
)
from internal_ai.app.config import Settings
from internal_ai.app.database import (
    Conversation,
    Message,
    RefreshTokens,
    Users,
    get_db,
)
from internal_ai.app.llm import LLMRateLimitError, LLMServiceError, ask

app = FastAPI()
app.add_middleware(IdempotencyMiddleware, backend=InMemoryBackend())
bearer_scheme = HTTPBearer()
settings = Settings()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class UserCreateRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=30, min_length=3)
    password: str = Field(min_length=12, max_length=128)


class UserCreateResponse(BaseModel):
    username: str


class ChatResponse(BaseModel):
    answer: str


class RateLimitResponse(BaseModel):
    detail: str
    retry_after: str | None


class ServiceErrorResponse(BaseModel):
    detail: str


class TokenResponse(BaseModel):
    token_type: str
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ConversationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationToken(BaseModel):
    access_token: str


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    content: str
    created_at: datetime


@app.get("/check")
def online():
    return {"status": "online"}


@app.post(
    "/auth/register",
    status_code=201,
    response_model=UserCreateResponse,
    responses={
        201: {"description": "User created succesfully"},
        409: {"description": "User already exists"},
    },
)
def add_user(create_user: UserCreateRequest, db=Depends(get_db)):
    hashed_password = hash_password(create_user.password)

    new_user = Users(username=create_user.username, password_hash=hashed_password)
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This username already exists")
    return UserCreateResponse(username=new_user.username)


@app.post(
    "/auth/login",
    status_code=200,
    response_model=TokenResponse,
    responses={
        404: {"description": "The following account doesn't exist"},
        401: {"description": "Unauthenticated"},
    },
)
def login(login_request: LoginRequest, db=Depends(get_db)):
    stmt = select(Users).where(Users.username == login_request.username)
    existing_user = db.scalars(stmt).one_or_none()
    if existing_user is None:
        raise HTTPException(status_code=404, detail="Account doesn't exist")
    if not verify_hashed_password(login_request.password, existing_user.password_hash):
        raise HTTPException(status_code=401, detail="Unauthenticated")

    token = create_token(existing_user.id)
    refresh_token, expiration = create_refresh_token()
    hash_refresh = hash_refresh_token(refresh_token)
    new_refresh_token = RefreshTokens(
        user_id=existing_user.id, token_hash=hash_refresh, expires_at=expiration
    )
    try:
        db.add(new_refresh_token)
        db.commit()
        db.refresh(new_refresh_token)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Could not save due to database error"
        )
    return {
        "token_type": "Bearer",
        "access_token": token,
        "refresh_token": refresh_token,
    }


@app.post(
    "/auth/refresh",
    response_model=TokenResponse,
    responses={
        401: {"description": "Invalid or expired refresh token"},
        409: {"description": "Failed to save due to database error"},
    },
)
def refresh_token(
    refresh_token: RefreshRequest,
    db=Depends(get_db),
):
    token_hash = hash_refresh_token(refresh_token.refresh_token)

    stmt = select(RefreshTokens).where(RefreshTokens.token_hash == token_hash)

    stored_token = db.scalars(stmt).one_or_none()

    if stored_token is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token",
        )

    if stored_token.revoked_at is not None:
        raise HTTPException(
            status_code=401,
            detail="Refresh token has been revoked",
        )

    if stored_token.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=401,
            detail="Refresh token has expired",
        )

    stmt = select(Users).where(Users.id == stored_token.user_id)
    user = db.scalars(stmt).one_or_none()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User no longer exists",
        )
    stored_token.revoked_at = datetime.now(UTC)
    token_refresh, expiration = create_refresh_token()
    hash_refreshed_token = hash_refresh_token(token_refresh)
    access_token = create_token(user.id)
    new_refresh_token = RefreshTokens(
        user_id=user.id, token_hash=hash_refreshed_token, expires_at=expiration
    )
    try:
        db.add(new_refresh_token)
        db.commit()
        db.refresh(new_refresh_token)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Failed to save due to database error"
        )

    return {
        "access_token": access_token,
        "refresh_token": token_refresh,
        "token_type": "bearer",
    }


@app.exception_handler(LLMServiceError)
async def llm_error_handler(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "The AI service is temporarily unavailable."},
    )


@app.exception_handler(LLMRateLimitError)
async def llm_error_rate_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit has been reached.",
            "retry_after": exc.retry_after,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(
        status_code=422, content={"detail": [error["msg"] for error in exc.errors()]}
    )


@app.post(
    "/conversations",
    status_code=201,
    response_model=ConversationResponse,
    responses={
        422: {"description": "title is empty or too long or not a string."},
        401: {
            "description": "Invalid or expired token,try refreshing the token via /auth/refresh"
        },
        500: {"description": "Failed to create conversation"},
    },
)
def create_conversation(
    conversation_request: ConversationCreateRequest,
    current_user: Users = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        new_conversation = Conversation(
            title=conversation_request.title, user_id=current_user.id
        )

        db.add(new_conversation)
        db.commit()
        db.refresh(new_conversation)
        return new_conversation
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create conversation")


@app.get(
    "/conversations",
    response_model=list[ConversationResponse],
    responses={
        401: {
            "description": "Invalid or expired token,try refreshing the token via /auth/refresh"
        },
        500: {"description": "Failed to retrieve conversations"},
    },
)
def get_conversations(
    current_user: Users = Depends(get_current_user), db=Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.user_id == current_user.id)
    )
    conversations = db.scalars(stmt).all()
    return conversations


@app.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    responses={
        401: {
            "description": "Invalid or expired token,try refreshing the token via /auth/refresh"
        },
        404: {"description": "Conversation not found"},
        500: {"description": "Failed to retrieve conversation"},
    },
)
def get_conversation(
    conversation_id: int,
    current_user: Users = Depends(get_current_user),
    db=Depends(get_db),
):
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == current_user.id
    )
    conversation = db.scalars(stmt).one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    responses={
        401: {
            "description": "Invalid or expired token,try refreshing the token via /auth/refresh"
        },
        404: {"description": "Conversation not found"},
        500: {"description": "Failed to delete conversation"},
    },
)
def delete_conversation(
    conversation_id: int,
    current_user: Users = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == current_user.id
        )
        conversation = db.scalars(stmt).one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        db.delete(conversation)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


@app.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatResponse],
    responses={
        401: {
            "description": "Invalid or expired token,try refreshing the token via /auth/refresh"
        },
        404: {"description": "Conversation not found"},
        500: {"description": "Failed to retrieve messages"},
    },
)
def get_conversation_messages(
    conversation_id: int,
    current_user: Users = Depends(get_current_user),
    db=Depends(get_db),
):

    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == current_user.id
    )
    conversation = db.scalars(stmt).one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conversation.messages
    return [ChatResponse(answer=message.content) for message in messages]


@app.post(
    "/conversations/{conversation_id}/messages",
    status_code=201,
    response_model=MessageResponse,
    responses={
        429: {
            "model": RateLimitResponse,
            "description": "The Gemini rate limit was exceeded",
        },
        503: {
            "model": ServiceErrorResponse,
            "description": "The AI service is temporarily unavailable",
        },
        422: {"description": "message is empty or too long or not a string."},
        401: {
            "description": "Invalid or expired token, try refreshing the token via /auth/refresh"
        },
        404: {"description": "Conversation not found"},
        500: {"description": "Failed to create message"},
    },
)
def create_conversation_message(
    conversation_id: int,
    chat_request: ChatRequest,
    current_user: Users = Depends(get_current_user),
    db=Depends(get_db),
):
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    )

    conversation = db.scalars(stmt).one_or_none()

    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=chat_request.message,
    )

    db.add(user_message)
    db.commit()

    assistant_response = ask(
        query=chat_request.message,
        user=current_user,
        conversation=conversation,
    )

    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=assistant_response,
    )
    try:
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        return assistant_message
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create message")
