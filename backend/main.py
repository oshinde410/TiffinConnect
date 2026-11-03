from __future__ import annotations

import json
import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal

import joblib
import jwt
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MinMaxScaler
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine, func, text, update
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tiffinconnect.db"
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(BASE_DIR / "models")))
MODEL_PATH = MODEL_DIR / "demand_lstm_v2.keras"
SCALER_PATH = MODEL_DIR / "demand_scaler_v2.joblib"
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"
SECRET_KEY = os.getenv("TIFFIN_SECRET", "")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("TIFFIN_SECRET must be set in production.")
    SECRET_KEY = "tiffinconnect-local-demo-secret-change-this-before-deployment"
if len(SECRET_KEY.encode("utf-8")) < 32:
    raise RuntimeError("TIFFIN_SECRET must contain at least 32 bytes.")
ALGORITHM = "HS256"
ENABLE_DEMAND_FORECAST = os.getenv(
    "ENABLE_DEMAND_FORECAST",
    "false" if IS_PRODUCTION else "true",
).strip().lower() in {"1", "true", "yes", "on"}
SEED_DEMO_DATA = os.getenv(
    "SEED_DEMO_DATA",
    "false" if IS_PRODUCTION else "true",
).strip().lower() in {"1", "true", "yes", "on"}
if IS_PRODUCTION and SEED_DEMO_DATA:
    raise RuntimeError("SEED_DEMO_DATA must be disabled in production.")

configured_origins = os.getenv("CORS_ORIGINS")
if configured_origins:
    CORS_ORIGINS = [origin.strip().rstrip("/") for origin in configured_origins.split(",") if origin.strip()]
elif IS_PRODUCTION:
    raise RuntimeError("Set CORS_ORIGINS to the deployed frontend origin in production.")
else:
    CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
if IS_PRODUCTION and "*" in CORS_ORIGINS:
    raise RuntimeError("CORS_ORIGINS must not contain a wildcard in production.")

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if IS_PRODUCTION and not DATABASE_URL.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError("Production DATABASE_URL must use PostgreSQL.")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine_options: Dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    if DATABASE_URL.startswith("postgresql+psycopg://"):
        engine_options["connect_args"] = {"prepare_threshold": None}
    elif DATABASE_URL.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, **engine_options)
elif IS_PRODUCTION:
    raise RuntimeError("DATABASE_URL must point to a persistent PostgreSQL database in production.")
else:
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
security = HTTPBearer()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="student")
    hostel = Column(String(120), default="Hostel Block A")
    budget = Column(Float, default=1800)
    veg_preference = Column(String(20), default="vegetarian")
    favorite_meal = Column(String(80), default="Paneer Bowl")
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", foreign_keys="Order.student_id", back_populates="student")
    cooked_orders = relationship("Order", foreign_keys="Order.cook_id", back_populates="cook")
    reviews = relationship("Review", back_populates="user")
    meals = relationship("Meal", back_populates="cook")


class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=False)
    price = Column(Float, nullable=False)
    category = Column(String(20), nullable=False)
    cook_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stock = Column(Integer, default=25)
    rating = Column(Float, default=4.5)
    prep_time = Column(String(25), default="25 mins")
    image_url = Column(String(255), default="https://images.unsplash.com/photo-1547592180-85f173990554")

    cook = relationship("User", back_populates="meals")
    orders = relationship("Order", back_populates="meal")
    reviews = relationship("Review", back_populates="meal")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cook_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meal_id = Column(Integer, ForeignKey("meals.id"), nullable=False)
    quantity = Column(Integer, default=1)
    total_price = Column(Float, nullable=False)
    plan_type = Column(String(30), default="daily")
    status = Column(String(30), default="confirmed")
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("User", foreign_keys=[student_id], back_populates="orders")
    cook = relationship("User", foreign_keys=[cook_id], back_populates="cooked_orders")
    meal = relationship("Meal", back_populates="orders")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meal_id = Column(Integer, ForeignKey("meals.id"), nullable=False)
    rating = Column(Float, nullable=False)
    comment = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="reviews")
    meal = relationship("Meal", back_populates="reviews")


class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6)
    role: Literal["student", "cook"] = "student"
    hostel: str | None = Field(default=None, max_length=120)
    budget: float | None = Field(default=None, gt=0)
    veg_preference: Literal["vegetarian", "non_vegetarian"] = "vegetarian"
    favorite_meal: str | None = Field(default=None, max_length=80)


class LoginInput(BaseModel):
    email: str
    password: str


class OrderInput(BaseModel):
    meal_id: int
    quantity: int = Field(default=1, ge=1, le=20)
    plan_type: Literal["daily", "weekly", "monthly"] = "daily"


class ReviewInput(BaseModel):
    meal_id: int
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=255)


class MealInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=500)
    price: float = Field(gt=0)
    category: Literal["veg", "non_veg"]
    stock: int = Field(default=1, ge=0, le=1000)
    prep_time: str = Field(default="25 mins", max_length=25)
    image_url: str = Field(
        default="https://images.unsplash.com/photo-1547592180-85f173990554",
        max_length=255,
    )


class OrderStatusInput(BaseModel):
    status: Literal["confirmed", "in_transit", "delivered", "cancelled"]


app = FastAPI(
    title="TiffinConnect API",
    version="1.0.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def require_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def as_user_payload(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "hostel": user.hostel,
        "budget": user.budget,
        "veg_preference": user.veg_preference,
        "favorite_meal": user.favorite_meal,
    }


def as_meal_payload(meal: Meal) -> Dict[str, Any]:
    return {
        "id": meal.id,
        "name": meal.name,
        "description": meal.description,
        "price": meal.price,
        "category": meal.category,
        "stock": meal.stock,
        "rating": meal.rating,
        "prep_time": meal.prep_time,
        "image_url": meal.image_url,
        "cook_name": meal.cook.name if meal.cook else "Home Kitchen",
        "cook_id": meal.cook_id,
        "review_count": len(meal.reviews),
    }


def as_order_payload(order: Order) -> Dict[str, Any]:
    return {
        "id": order.id,
        "meal_id": order.meal_id,
        "meal_name": order.meal.name if order.meal else "Meal",
        "cook_name": order.cook.name if order.cook else "Kitchen",
        "student_name": order.student.name if order.student else "Student",
        "quantity": order.quantity,
        "total_price": order.total_price,
        "status": order.status,
        "plan_type": order.plan_type,
        "created_at": order.created_at.isoformat() if order.created_at else "",
    }


def seed_demo_data(db: Session) -> None:
    if db.query(User).count() > 0:
        return

    admin = User(
        name="Admin User",
        email="admin@tiffinconnect.com",
        hashed_password=hash_password("admin123"),
        role="admin",
        hostel="Admin Office",
        budget=2000,
        veg_preference="vegetarian",
        favorite_meal="Paneer Bowl",
    )
    arjun = User(
        name="Arjun Sharma",
        email="arjun@student.tiffin",
        hashed_password=hash_password("student123"),
        role="student",
        hostel="Boys Hostel - Block A",
        budget=1800,
        veg_preference="vegetarian",
        favorite_meal="Paneer Bowl",
    )
    meera = User(
        name="Meera Nair",
        email="meera@student.tiffin",
        hashed_password=hash_password("student123"),
        role="student",
        hostel="Girls Hostel - Block C",
        budget=2200,
        veg_preference="vegetarian",
        favorite_meal="Dal Khichdi",
    )
    asha = User(
        name="Asha Kitchen",
        email="asha@cook.tiffin",
        hashed_password=hash_password("cook123"),
        role="cook",
        hostel="Gurunanak Colony",
        budget=0,
        veg_preference="vegetarian",
        favorite_meal="Paneer Bowl",
    )
    neha = User(
        name="Neha Home Foods",
        email="neha@cook.tiffin",
        hashed_password=hash_password("cook123"),
        role="cook",
        hostel="Laxmi Nagar",
        budget=0,
        veg_preference="non_vegetarian",
        favorite_meal="Chicken Curry",
    )

    db.add_all([admin, arjun, meera, asha, neha])
    db.commit()

    meals = [
        Meal(
            name="Paneer Tawa Bowl",
            description="Soft paneer cubes with tawa vegetables and fresh roti.",
            price=150,
            category="veg",
            cook_id=asha.id,
            stock=30,
            rating=4.8,
            prep_time="25 mins",
            image_url="https://images.unsplash.com/photo-1604908176997-125f25cc6f3d",
        ),
        Meal(
            name="Dal Khichdi",
            description="Comforting khichdi made with moong dal, rice, ghee and seasonal vegetables.",
            price=120,
            category="veg",
            cook_id=asha.id,
            stock=35,
            rating=4.7,
            prep_time="20 mins",
            image_url="https://images.unsplash.com/photo-1547592180-85f173990554",
        ),
        Meal(
            name="Veg Pulao",
            description="Fragrant rice with vegetables and mild spices for a balanced midday meal.",
            price=140,
            category="veg",
            cook_id=asha.id,
            stock=25,
            rating=4.6,
            prep_time="30 mins",
            image_url="https://images.unsplash.com/photo-1512058564366-18510be2db19",
        ),
        Meal(
            name="Chicken Curry",
            description="Homestyle chicken curry with gravy served with jeera rice.",
            price=180,
            category="non_veg",
            cook_id=neha.id,
            stock=18,
            rating=4.9,
            prep_time="35 mins",
            image_url="https://images.unsplash.com/photo-1603894584373-5ac82b2ae398",
        ),
        Meal(
            name="Egg Biryani",
            description="Aromatic biryani with eggs, herbs and saffron-flavored rice.",
            price=170,
            category="non_veg",
            cook_id=neha.id,
            stock=22,
            rating=4.5,
            prep_time="33 mins",
            image_url="https://images.unsplash.com/photo-1631452180519-c014fe946bc7",
        ),
        Meal(
            name="Soya Chana Bowl",
            description="High-protein soy and chana combo with a crunchy vegetable base.",
            price=160,
            category="veg",
            cook_id=asha.id,
            stock=20,
            rating=4.6,
            prep_time="28 mins",
            image_url="https://images.unsplash.com/photo-1546793665-c74683f339c1",
        ),
        Meal(
            name="Mixed Veg Thali",
            description="Rice, daal, sabzi, salad and roti in a wholesome thali format.",
            price=200,
            category="veg",
            cook_id=asha.id,
            stock=28,
            rating=4.8,
            prep_time="40 mins",
            image_url="https://images.unsplash.com/photo-1544025162-d76694265947",
        ),
        Meal(
            name="Fish Rice Combo",
            description="Flavourful fish fillet with rice and fries prepared daily.",
            price=220,
            category="non_veg",
            cook_id=neha.id,
            stock=16,
            rating=4.7,
            prep_time="30 mins",
            image_url="https://images.unsplash.com/photo-1519708227418-c8fd9a32b7a2",
        ),
    ]
    db.add_all(meals)
    db.commit()

    meal_ids = [meal.id for meal in meals]
    orders = [
        Order(
            student_id=arjun.id,
            cook_id=asha.id,
            meal_id=meal_ids[0],
            quantity=2,
            total_price=300,
            plan_type="monthly",
            status="delivered",
            created_at=datetime.utcnow() - timedelta(days=1),
        ),
        Order(
            student_id=arjun.id,
            cook_id=neha.id,
            meal_id=meal_ids[3],
            quantity=1,
            total_price=180,
            plan_type="daily",
            status="in_transit",
            created_at=datetime.utcnow() - timedelta(days=3),
        ),
        Order(
            student_id=meera.id,
            cook_id=asha.id,
            meal_id=meal_ids[1],
            quantity=1,
            total_price=120,
            plan_type="daily",
            status="delivered",
            created_at=datetime.utcnow() - timedelta(days=5),
        ),
        Order(
            student_id=meera.id,
            cook_id=neha.id,
            meal_id=meal_ids[4],
            quantity=2,
            total_price=340,
            plan_type="monthly",
            status="confirmed",
            created_at=datetime.utcnow() - timedelta(days=7),
        ),
    ]
    db.add_all(orders)

    reviews = [
        Review(user_id=arjun.id, meal_id=meal_ids[0], rating=5, comment="Fresh, hygienic and tasty."),
        Review(user_id=meera.id, meal_id=meal_ids[1], rating=4, comment="Healthy and filling for hostel life."),
    ]
    db.add_all(reviews)
    db.commit()


def bootstrap_admin(db: Session) -> None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if bool(email) != bool(password):
        raise RuntimeError(
            "Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD to create the initial admin."
        )
    if not email:
        return
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL must be a valid email address.")
    if len(password) < 12:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters.")

    admin = db.query(User).filter(User.email == email).first()
    if admin:
        if admin.role != "admin":
            raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL is already assigned to a non-admin account.")
        return
    db.add(
        User(
            name=os.getenv("BOOTSTRAP_ADMIN_NAME", "").strip() or "TiffinConnect Admin",
            email=email,
            hashed_password=hash_password(password),
            role="admin",
            hostel="Admin Office",
            budget=0,
            veg_preference="vegetarian",
            favorite_meal="",
        )
    )
    db.commit()


@app.on_event("startup")
def startup_event() -> None:
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=engine)
        if SEED_DEMO_DATA:
            seed_demo_data(db)
        bootstrap_admin(db)
    finally:
        db.close()


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "message": "TiffinConnect backend is online."}


@app.post("/api/auth/register")
def register(payload: RegisterInput, db: Session = Depends(get_db)) -> Dict[str, Any]:
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Name cannot be blank.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="User already exists.")

    user = User(
        name=payload.name.strip(),
        email=email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        hostel=payload.hostel or "Hostel Block A",
        budget=payload.budget if payload.budget is not None else 1800,
        veg_preference=payload.veg_preference,
        favorite_meal=payload.favorite_meal or "Paneer Bowl",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user), "user": as_user_payload(user)}


@app.post("/api/auth/login")
def login(payload: LoginInput, db: Session = Depends(get_db)) -> Dict[str, Any]:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return {"token": create_token(user), "user": as_user_payload(user)}


@app.get("/api/me")
def get_me(current_user: User = Depends(require_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"user": as_user_payload(current_user), "dashboard": build_dashboard_for_role(db, current_user)}


@app.get("/api/meals")
def list_meals(
    search: str | None = Query(default=None, max_length=120),
    category: Literal["veg", "non_veg"] | None = None,
    cook_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query = db.query(Meal)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(Meal.name.ilike(term) | Meal.description.ilike(term))
    if category:
        query = query.filter(Meal.category == category)
    if cook_id:
        query = query.filter(Meal.cook_id == cook_id)
    meals = query.order_by(Meal.rating.desc(), Meal.name.asc()).all()
    return {"meals": [as_meal_payload(meal) for meal in meals]}


@app.post("/api/meals", status_code=status.HTTP_201_CREATED)
def create_meal(
    payload: MealInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Dict[str, Any]:
    if current_user.role != "cook":
        raise HTTPException(status_code=403, detail="Only cooks can create meals.")
    meal = Meal(**payload.model_dump(), cook_id=current_user.id)
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return {"meal": as_meal_payload(meal)}


@app.put("/api/meals/{meal_id}")
def update_meal(
    meal_id: int,
    payload: MealInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Dict[str, Any]:
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found.")
    if current_user.role != "cook" or meal.cook_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own meals.")
    for field, value in payload.model_dump().items():
        setattr(meal, field, value)
    db.commit()
    db.refresh(meal)
    return {"meal": as_meal_payload(meal)}


@app.delete("/api/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> None:
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found.")
    if current_user.role != "cook" or meal.cook_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own meals.")
    if db.query(Order).filter(Order.meal_id == meal.id).first():
        raise HTTPException(status_code=409, detail="Meals with order history cannot be deleted.")
    db.delete(meal)
    db.commit()


@app.post("/api/orders")
def create_order(payload: OrderInput, db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can place orders.")

    meal = db.query(Meal).filter(Meal.id == payload.meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found.")
    if meal.category == "non_veg" and current_user.veg_preference == "vegetarian":
        raise HTTPException(status_code=400, detail="This meal does not match your vegetarian preference.")

    quantity = payload.quantity
    stock_update = db.execute(
        update(Meal)
        .where(Meal.id == meal.id, Meal.stock >= quantity)
        .values(stock=Meal.stock - quantity)
    )
    if stock_update.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Not enough portions are available.")

    total_price = round(float(meal.price) * quantity, 2)
    order = Order(
        student_id=current_user.id,
        cook_id=meal.cook_id,
        meal_id=meal.id,
        quantity=quantity,
        total_price=total_price,
        plan_type=payload.plan_type,
        status="confirmed",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return {"message": "Order placed successfully.", "order": as_order_payload(order)}


@app.patch("/api/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: OrderStatusInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Dict[str, Any]:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if current_user.role != "admin" and (
        current_user.role != "cook" or order.cook_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="You can only update orders for your kitchen.")
    if order.status in {"delivered", "cancelled"}:
        raise HTTPException(status_code=409, detail="This order can no longer be updated.")
    if payload.status == "cancelled":
        db.query(Meal).filter(Meal.id == order.meal_id).update(
            {Meal.stock: Meal.stock + order.quantity},
            synchronize_session="fetch",
        )
    order.status = payload.status
    db.commit()
    db.refresh(order)
    return {"order": as_order_payload(order)}


@app.get("/api/meals/{meal_id}/reviews")
def list_meal_reviews(meal_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found.")
    reviews = (
        db.query(Review)
        .filter(Review.meal_id == meal_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    return {
        "reviews": [
            {
                "id": review.id,
                "student_name": review.user.name,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat(),
            }
            for review in reviews
        ]
    }


@app.post("/api/reviews")
def add_review(payload: ReviewInput, db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can leave reviews.")
    meal = db.query(Meal).filter(Meal.id == payload.meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found.")
    delivered_order = (
        db.query(Order)
        .filter(
            Order.student_id == current_user.id,
            Order.meal_id == meal.id,
            Order.status == "delivered",
        )
        .first()
    )
    if not delivered_order:
        raise HTTPException(status_code=403, detail="You can review a meal after it has been delivered.")

    review = (
        db.query(Review)
        .filter(Review.user_id == current_user.id, Review.meal_id == meal.id)
        .first()
    )
    if review:
        review.rating = float(payload.rating)
        review.comment = payload.comment.strip()
    else:
        review = Review(
            user_id=current_user.id,
            meal_id=meal.id,
            rating=float(payload.rating),
            comment=payload.comment.strip(),
        )
        db.add(review)
    db.commit()

    average = db.query(func.avg(Review.rating)).filter(Review.meal_id == meal.id).scalar() or 0.0
    meal.rating = round(float(average), 2)
    db.commit()
    return {"message": "Review submitted successfully.", "average_rating": meal.rating}


@app.get("/api/student/dashboard")
def student_dashboard(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can access this dashboard.")
    return build_dashboard_for_role(db, current_user)


@app.get("/api/cook/dashboard")
def cook_dashboard(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "cook":
        raise HTTPException(status_code=403, detail="Only cooks can access this dashboard.")
    return build_dashboard_for_role(db, current_user)


@app.get("/api/admin/dashboard")
def admin_dashboard(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can access this dashboard.")
    return build_dashboard_for_role(db, current_user)


@app.get("/api/demand/prediction")
def demand_prediction(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role not in {"cook", "admin"}:
        raise HTTPException(status_code=403, detail="This feature is available to cooks and admins.")
    if not ENABLE_DEMAND_FORECAST:
        raise HTTPException(
            status_code=503,
            detail="Demand forecasting is disabled on this deployment. Enable the ML dependencies and set ENABLE_DEMAND_FORECAST=true.",
        )
    return build_demand_prediction_payload()


@app.get("/api/recommendations")
def recommendations_endpoint(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> Dict[str, Any]:
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can see meal recommendations.")
    return {"recommendations": recommend_meals_for_student(db, current_user)}


def build_dashboard_for_role(db: Session, current_user: User) -> Dict[str, Any]:
    if current_user.role == "student":
        meals = db.query(Meal).order_by(Meal.rating.desc()).limit(6).all()
        recommendations = recommend_meals_for_student(db, current_user)
        orders = (
            db.query(Order)
            .filter(Order.student_id == current_user.id)
            .order_by(Order.created_at.desc())
            .limit(4)
            .all()
        )
        now = datetime.utcnow()
        student_orders = db.query(Order).filter(Order.student_id == current_user.id).all()
        monthly_total = sum(
            order.total_price
            for order in student_orders
            if order.created_at
            and order.created_at.month == now.month
            and order.created_at.year == now.year
            and order.status != "cancelled"
        )
        subscriptions = sum(
            1
            for order in student_orders
            if order.plan_type != "daily" and order.status in {"confirmed", "in_transit"}
        )
        return {
            "summary": {
                "todayMeals": len(meals),
                "recommended": len(recommendations),
                "activeSubscriptions": subscriptions,
                "recentOrders": len(orders),
                "monthlyExpenditure": round(monthly_total, 2),
            },
            "meals": [as_meal_payload(meal) for meal in meals],
            "recommendations": recommendations,
            "orders": [as_order_payload(order) for order in orders],
            "favorites": [as_meal_payload(meal) for meal in meals[:3]],
        }

    if current_user.role == "cook":
        orders = db.query(Order).filter(Order.cook_id == current_user.id).order_by(Order.created_at.desc()).limit(5).all()
        meals = db.query(Meal).filter(Meal.cook_id == current_user.id).all()
        all_orders = db.query(Order).filter(Order.cook_id == current_user.id).all()
        revenue = sum(
            order.total_price for order in all_orders if order.status != "cancelled"
        )
        today = date.today()
        today_orders = sum(
            1
            for order in all_orders
            if order.status != "cancelled"
            and order.created_at
            and order.created_at.date() == today
        )
        popular = []
        for meal in meals:
            sold = sum(
                order.quantity for order in meal.orders if order.status != "cancelled"
            )
            if sold > 0:
                popular.append({"name": meal.name, "sold": sold})
        demand = (
            build_demand_prediction_payload()
            if ENABLE_DEMAND_FORECAST
            else {
                "enabled": False,
                "explanation": "Forecasting is disabled on this resource-constrained deployment. Enable the ML dependencies and set ENABLE_DEMAND_FORECAST=true on a service with sufficient memory.",
            }
        )
        return {
            "summary": {
                "todayOrders": today_orders,
                "totalRevenue": round(revenue, 2),
                "popularMeals": len(popular),
                "avgRating": round(sum(meal.rating for meal in meals) / len(meals), 2) if meals else 0,
            },
            "orders": [as_order_payload(order) for order in orders],
            "popular_meals": sorted(popular, key=lambda item: item["sold"], reverse=True)[:3],
            "demand": demand,
            "meals": [as_meal_payload(meal) for meal in meals],
        }

    students = db.query(User).filter(User.role == "student").count()
    cooks = db.query(User).filter(User.role == "cook").count()
    total_orders = db.query(Order).count()
    total_revenue = (
        db.query(func.sum(Order.total_price))
        .filter(Order.status != "cancelled")
        .scalar()
        or 0
    )
    return {
        "summary": {
            "students": students,
            "cooks": cooks,
            "orders": total_orders,
            "revenue": round(float(total_revenue), 2),
        },
        "recent_orders": [as_order_payload(order) for order in db.query(Order).order_by(Order.created_at.desc()).limit(5).all()],
        "top_meals": [as_meal_payload(meal) for meal in db.query(Meal).order_by(Meal.rating.desc()).limit(5).all()],
    }


def generate_synthetic_demand_series(days: int = 180) -> pd.DataFrame:
    start = date.today() - timedelta(days=days)
    rng = random.Random(42)
    rows = []
    for offset in range(days):
        current_day = start + timedelta(days=offset)
        weekday = current_day.weekday()
        weekend = 1 if weekday >= 5 else 0
        festival = 1 if current_day.month in {10, 11, 12} and current_day.day in {15, 20, 25, 30} else 0
        weather = 1.0 + abs(math.sin((offset + 1) / 6.5)) * 0.55
        base = 28 + (weekend * 16) + (festival * 12)
        trend = math.sin(offset / 9) * 10
        noise = rng.uniform(-7, 7)
        demand = max(10, int(round((base + trend) * weather + noise)))
        rows.append(
            {
                "date": current_day.isoformat(),
                "orders": demand,
                "day_of_week": weekday,
                "weekend": weekend,
                "festival": festival,
                "weather_index": round(weather, 2),
            }
        )
    return pd.DataFrame(rows)


def get_keras():
    try:
        from tensorflow import keras
    except ImportError as exc:
        raise RuntimeError(
            "Demand forecasting dependencies are not installed. Install backend/requirements-ml.txt."
        ) from exc
    return keras


def ensure_lstm_model_exists(force: bool = False) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not force and MODEL_PATH.exists() and SCALER_PATH.exists():
        return

    keras = get_keras()
    df = generate_synthetic_demand_series(180)
    sequence_length = 14
    features = df[["orders", "day_of_week", "weekend", "festival", "weather_index"]]
    split_index = int(len(features) * 0.8)
    scaler = MinMaxScaler()
    scaled_features = scaler.fit(features.iloc[:split_index]).transform(features)

    X, y = [], []
    for idx in range(split_index - sequence_length):
        X.append(scaled_features[idx : idx + sequence_length])
        y.append(scaled_features[idx + sequence_length, 0])

    X_array = np.array(X, dtype=np.float32)
    y_array = np.array(y, dtype=np.float32)

    keras.utils.set_random_seed(42)
    model = keras.Sequential(
        [
            keras.layers.Input(shape=(sequence_length, scaled_features.shape[1])),
            keras.layers.LSTM(64, return_sequences=True),
            keras.layers.Dropout(0.2),
            keras.layers.LSTM(32),
            keras.layers.Dense(16, activation="relu"),
            keras.layers.Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse")
    model.fit(X_array, y_array, epochs=18, batch_size=16, verbose=0)
    model.save(MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)


def load_lstm_components() -> tuple[Any, MinMaxScaler]:
    ensure_lstm_model_exists(force=False)
    keras = get_keras()
    model = keras.models.load_model(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return model, scaler


def build_demand_prediction_payload() -> Dict[str, Any]:
    df = generate_synthetic_demand_series(180)
    model, scaler = load_lstm_components()
    sequence_length = 14
    feature_cols = ["orders", "day_of_week", "weekend", "festival", "weather_index"]
    scaled = scaler.transform(df[feature_cols])

    history = [{"date": row["date"], "orders": row["orders"]} for row in df.tail(14).to_dict("records")]
    last_seq = scaled[-sequence_length:]
    predictions = []

    current_window = last_seq.copy()
    for offset in range(7):
        future_day = date.today() + timedelta(days=offset + 1)
        next_fut = model.predict(current_window[np.newaxis, :, :], verbose=0)[0][0]
        predicted_orders = float((next_fut - scaler.min_[0]) / scaler.scale_[0])
        future_row = {
            "orders": predicted_orders,
            "day_of_week": future_day.weekday(),
            "weekend": 1 if future_day.weekday() >= 5 else 0,
            "festival": 1 if future_day.month in {10, 11, 12} and future_day.day in {15, 20, 25, 30} else 0,
            "weather_index": 1.0 + abs(math.sin((len(df) + offset) / 6.5)) * 0.55,
        }
        future_scaled = scaler.transform(pd.DataFrame([future_row], columns=feature_cols))[0]
        current_window = np.vstack([current_window[1:], future_scaled])
        predictions.append({
            "day": future_day.strftime("%a"),
            "predicted_orders": max(12, int(round(predicted_orders))),
        })

    split_index = int(len(df) * 0.8)
    validation_errors = []
    for target_index in range(split_index, len(df)):
        validation_window = scaled[target_index - sequence_length : target_index]
        predicted_scaled = float(
            model.predict(validation_window[np.newaxis, :, :], verbose=0)[0][0]
        )
        predicted_orders = (predicted_scaled - scaler.min_[0]) / scaler.scale_[0]
        validation_errors.append(abs(float(df.iloc[target_index]["orders"]) - predicted_orders))
    mae = float(np.mean(validation_errors)) if validation_errors else 0.0

    prep_quantity = int(round(sum(item["predicted_orders"] for item in predictions) / len(predictions) + 6))
    explanation = (
        "This demand forecast is based on a synthetic 180-day LSTM model trained on order trends, weekends, holidays, and weather-style demand signals. "
        "The model labels the output as a demo and recommends a small preparation buffer to reduce waste."
    )

    return {
        "history": history,
        "forecast": predictions,
        "holdout_mae": round(mae, 2),
        "suggested_preparation": prep_quantity,
        "explanation": explanation,
        "synthetic_note": "Demo prediction generated from synthetic demand data for academic demonstration.",
    }


def feature_vector_for_user(user: User, meal: Meal) -> List[float]:
    veg_match = 1.0 if user.veg_preference == "vegetarian" and meal.category == "veg" else 0.0
    non_veg_match = 1.0 if user.veg_preference == "non_vegetarian" and meal.category == "non_veg" else 0.0
    budget_fit = max(0.0, 1.0 - meal.price / max(1.0, user.budget))
    favorite_match = 1.0 if user.favorite_meal and user.favorite_meal.lower() in meal.name.lower() else 0.0
    rating_score = meal.rating / 5.0
    stock_score = min(1.0, meal.stock / 30)
    return [veg_match, non_veg_match, budget_fit, favorite_match, rating_score, stock_score]


def recommend_meals_for_student(db: Session, student: User) -> List[Dict[str, Any]]:
    meals = db.query(Meal).filter(Meal.stock > 0).all()
    if not meals:
        return []

    rows: List[List[float]] = []
    labels: List[int] = []
    for user in db.query(User).filter(User.role == "student").all():
        for meal in meals:
            rows.append(feature_vector_for_user(user, meal))
            preference_match = (
                user.veg_preference == "vegetarian" and meal.category == "veg"
            ) or (
                user.veg_preference == "non_vegetarian" and meal.category == "non_veg"
            )
            favorite_match = bool(
                user.favorite_meal and user.favorite_meal.lower() in meal.name.lower()
            )
            label = 1 if preference_match or favorite_match else 0
            labels.append(label)

    model = MLPClassifier(
        hidden_layer_sizes=(10,),
        max_iter=500,
        random_state=42,
        solver="lbfgs",
    )
    model.fit(rows, labels)

    scored: List[Dict[str, Any]] = []
    for meal in meals:
        if student.veg_preference == "vegetarian" and meal.category != "veg":
            continue
        if student.veg_preference == "non_vegetarian" and meal.category != "non_veg":
            continue
        vector = feature_vector_for_user(student, meal)
        probability = float(model.predict_proba([vector])[0][1])
        scored.append({"meal": as_meal_payload(meal), "score": round(probability, 3)})

    scored.sort(key=lambda item: item["score"], reverse=True)
    return [{**entry["meal"], "match_score": entry["score"]} for entry in scored[:4]]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
