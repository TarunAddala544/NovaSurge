from sqlalchemy import Column, Integer, String, Float
from database import Base
from pydantic import BaseModel
from typing import Optional


class ProductORM(Base):
    __tablename__ = "products"

    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String(255), nullable=False)
    price    = Column(Float, nullable=False)
    stock    = Column(Integer, nullable=False, default=0)
    category = Column(String(100), nullable=False)


class ProductCreate(BaseModel):
    name: str
    price: float
    stock: int
    category: str


class ProductResponse(BaseModel):
    id: int
    name: str
    price: float
    stock: int
    category: str

    class Config:
        from_attributes = True
