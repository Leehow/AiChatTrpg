from pydantic import BaseModel


class OkResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
