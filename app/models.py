from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from .database import Base
import enum

# Enums
class UserStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"

class SubmissionType(str, enum.Enum):
    draft = "draft"
    final = "final"

class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"

class Language(str, enum.Enum):
    english = "English"
    spanish = "Spanish"
    french = "French"

class Timezone(str, enum.Enum):
    utc = "UTC"
    est = "EST"
    pst = "PST"

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    full_name = Column(String, nullable=True)
    phone_number = Column(String, nullable=True)
    specialization = Column(String, nullable=True)
    education_background = Column(String, nullable=True)
    work_experience = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    status = Column(Enum(UserStatus), default=UserStatus.active, nullable=False)
    rating = Column(Float, default=0.0, nullable=False)
    email_notifications = Column(Boolean, default=True)
    push_notifications = Column(Boolean, default=True)
    weekly_reports = Column(Boolean, default=True)
    system_updates = Column(Boolean, default=True)
    default_language = Column(Enum(Language), default=Language.english, nullable=False)
    default_timezone = Column(Enum(Timezone), default=Timezone.utc, nullable=False)
    balance = Column(Float, default=0.0, nullable=False)

    # Relationships
    profile = relationship("Profile", back_populates="user", uselist=False)
    bids = relationship("Bid", back_populates="writer")
    orders = relationship("Order", back_populates="client", foreign_keys="Order.client_id")
    assigned_orders = relationship("Order", back_populates="writer", foreign_keys="Order.writer_id")
    notifications = relationship("Notification", back_populates="user")
    submissions = relationship("Submission", back_populates="writer")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_blocked = Column(Boolean, default=False)

    # Relationships
    order = relationship("Order", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)
    service = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    level = Column(String, nullable=False)
    language = Column(String, nullable=False)
    words = Column(Integer, nullable=False)
    title = Column(String, index=True, nullable=False)
    description = Column(String, nullable=False)
    client_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    writer_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    price = Column(Float, nullable=False)
    deadline = Column(DateTime, nullable=False, index=True)
    styles = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(String, default="pending")
    response_time = Column(Float, nullable=True)
    selected_bid_id = Column(Integer, ForeignKey("bids.id"), nullable=True)
    file_path = Column(String, nullable=True)
    rating = Column(Float, nullable=True)

    # Relationships
    bids = relationship("Bid", back_populates="order", foreign_keys="Bid.order_id")
    client = relationship("User", back_populates="orders", foreign_keys=[client_id])
    writer = relationship("User", back_populates="assigned_orders", foreign_keys=[writer_id])
    selected_bid = relationship("Bid", foreign_keys=[selected_bid_id])
    messages = relationship("Message", back_populates="order")
    submissions = relationship("Submission", back_populates="order")

class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    writer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    delivery_time = Column(DateTime, nullable=True)
    message_to_client = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="bids", foreign_keys=[order_id])
    writer = relationship("User", back_populates="bids")

class Profile(Base):
    __tablename__ = 'profiles'
    id = Column(Integer, primary_key=True, index=True)
    nickname = Column(String, nullable=False)
    short_about = Column(String, nullable=True)
    long_about = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    avatar = Column(String, nullable=True)

    # Relationships
    user = relationship("User", back_populates="profile")

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="notifications")

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(days=1), nullable=False)
    used = Column(Boolean, default=False)

    user = relationship("User", back_populates="password_reset_tokens")

class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    writer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    submission_type = Column(Enum(SubmissionType), nullable=False)
    file_path = Column(String, nullable=True)
    content = Column(String, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.pending, nullable=False)
    feedback = Column(String, nullable=True)

    # Relationships
    order = relationship("Order", back_populates="submissions")
    writer = relationship("User", back_populates="submissions")