import os
import re
from enum import Enum

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

app = FastAPI()
router: APIRouter = APIRouter(prefix="/orders")


class OrderState(str, Enum):
    NEW: str = "new"
    PAID = "paid"
    SHIPPED = "shipped"


class Payments:
    TRANSITIONS = {OrderState.NEW: [OrderState.PAID]}  # noqa: RUF012


class OrderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    token: re.Pattern[bytes] = re.compile(pattern=b"x")

    @field_validator("title")
    @classmethod
    def not_blank(cls, value: str) -> str:
        return value.strip()


def require_role(role: str):
    return lambda: role


@router.post("/{order_id}/ship")
@router.post("/{order_id}/dispatch", dependencies=[Depends(require_role("ops"))])
def ship(order_id: int, _: str = Depends(require_role("admin"))):
    if order_id < 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="missing")
    if os.getenv("SHIP_MODE") == "fast":
        return {"state": OrderState.SHIPPED}
    if hook := os.getenv("NOTIFIER_URL"):
        return {"hook": hook}
    return {}


app.include_router(router)
