from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from database import Base
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PaymentORM(Base):
    __tablename__ = "payments"

    id         = Column(Integer, primary_key=True, index=True)
    order_id   = Column(Integer, nullable=False)
    amount     = Column(Float, nullable=False)
    status     = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PaymentCreate(BaseModel):
    order_id: int
    amount: float


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    amount: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
