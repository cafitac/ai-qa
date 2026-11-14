import os
from enum import Enum

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

app = FastAPI()
router = APIRouter(prefix="/orders")


class OrderState(str, Enum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"


TRANSITIONS = {
    OrderState.NEW: [OrderState.PAID],
    OrderState.PAID: [OrderState.SHIPPED],
}


class OrderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value: str) -> str:
        return value.strip()


def get_current_user() -> str:
    return "user"


def require_role(role: str):
    return lambda: role


@router.post("", status_code=201)
def create_order(payload: OrderCreate, user: str = Depends(get_current_user)):
    return payload


@router.post("/{order_id}/ship")
def ship(order_id: int, _: str = Depends(require_role("admin"))):
    if order_id < 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="missing")
    if os.getenv("SHIPPING_ENABLED") == "1":
        return {"state": OrderState.SHIPPED}
    if hook := os.getenv("NOTIFIER_URL"):
        return {"hook": hook}
    return {}


app.include_router(router)
