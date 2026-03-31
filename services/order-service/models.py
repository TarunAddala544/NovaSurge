from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OrderORM(Base):
    __tablename__ = "orders"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(String(100), nullable=False)
    product_id = Column(Integer, nullable=False)
    quantity   = Column(Integer, nullable=False)
    status     = Column(String(50), nullable=False, default="pending")
    payment_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OrderCreate(BaseModel):
    user_id: str
    product_id: int
    quantity: int


class OrderResponse(BaseModel):
    id: int
    user_id: str
    product_id: int
    quantity: int
    status: str
    payment_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
