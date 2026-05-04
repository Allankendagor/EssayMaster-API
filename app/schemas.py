from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict
from datetime import datetime,timezone
from enum import Enum

# Enums
class SubmissionType(str, Enum):
    draft = "draft"
    final = "final"

class SubmissionStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"

# Base User Schemas
class UserCreate(BaseModel):
    email: EmailStr
    username: Optional[str] = None
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    password: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    specialization: Optional[str] = None
    education_background: Optional[str] = None
    work_experience: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    default_language: Optional[str] = None
    default_timezone: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    role: str
    full_name: Optional[str] = None
    created_at: datetime
    status: Optional[str] = None
    rating: Optional[float] = None
    class Config:
        from_attributes = True

# Messages Schemas
class MessageCreate(BaseModel):
    order_id: Optional[int] = None  
    recipient_id: Optional[int] = None  
    content: str

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    order_id: int
    sender_id: int
    recipient_id: int
    content: str
    timestamp: datetime
    is_blocked: bool
    sender_username: Optional[str]

    class Config:
        from_attributes = True

class DelMessageResponse(BaseModel):
    detail: str

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str
    role: str

class TokenData(BaseModel):
    id: Optional[int] = None
    role: Optional[str] = None

# Profile Schemas
class OrderHistoryEntry(BaseModel):
    order_id: int
    date: datetime
    status: str
    writer: str  # The endpoint always provides a string (either a username or "No proposals yet")
    paid: bool  # Matches the endpoint's boolean response (True/False)
    rating: Optional[float] = None  # Matches the endpoint (None for unrated orders)

    class Config:
        from_attributes = True

class Profile1(BaseModel):
    user_id: int
    join_date: datetime
    balance: float
    notifications_count: int
    orders_count: int
    acceptance_rate: float
    pay_rate: float
    orders_history: List[OrderHistoryEntry]
    email: str
    role: str
    avatar: Optional[str] = None

    class Config:
        from_attributes = True

class ProfileResponse(BaseModel):
    id: int
    nickname: str
    short_about: Optional[str] = None
    long_about: Optional[str] = None
    user_id: int
    created_at: datetime
    avatar: Optional[str] = None

    class Config:
        from_attributes = True

# Writer Schemas
class WriterCreate(BaseModel):
    full_name: Optional[str] = None
    email: EmailStr
    password: str
    phone_number: Optional[str] = None
    specialization: Optional[str] = None
    education_background: Optional[str] = None
    work_experience: Optional[str] = None
    bio: Optional[str] = None

class WriterUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None
    specialization: Optional[str] = None
    education_background: Optional[str] = None
    work_experience: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None

# Updated WriterResponse to match the endpoint's response
class WriterResponse(BaseModel):
    id: int
    name: str
    avatar: Optional[str]
    isOnline: bool
    rating: float
    reviews: str
    orders: str
    successRate: int
    description: str
    expertise: List[str]

    class Config:
        from_attributes = True

# Schema for the list of writers
class WritersResponse(BaseModel):
    writers: List[WriterResponse]
    
class WriterProfileResponse(BaseModel):
    writer: WriterResponse
    pending_works: List['OrderResponse']
    completed_works: List['OrderResponse']

# Order Schemas
class OrderCreate(BaseModel):
    type: str
    service: str
    subject: str
    level: str
    language: str
    words: int
    title: str
    description: str
    price: float
    deadline_date: str  # e.g., "2025-04-23"
    deadline_time: str  # e.g., "16:28"
    styles: str
    deadline: Optional[datetime] = None  # Computed field, not provided in request

    @validator("deadline", pre=True, always=True)
    def combine_deadline(cls, v, values):
        if "deadline_date" not in values or "deadline_time" not in values:
            raise ValueError("deadline_date and deadline_time are required")
        try:
            deadline_str = f"{values['deadline_date']} {values['deadline_time']}"
            return datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("Invalid date or time format. Use YYYY-MM-DD for date and HH:MM for time.")

    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    id: int
    type: str
    service: str
    subject: str
    level: str
    language: str
    words: int
    title: str
    description: str
    client_id: int
    writer_id: Optional[int] = None
    price: float
    deadline: datetime
    styles: str
    selected_bid_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    is_active: bool
    status: str
    response_time: Optional[float] = None
    file_path: Optional[str] = None
    rating: Optional[float] = None
    class Config:
        from_attributes = True

class BidCreate(BaseModel):
    amount: float
    delivery_time: Optional[datetime]
    message_to_client: Optional[str] = None

    @validator("delivery_time")
    def ensure_delivery_time_timezone(cls, value):
        if value and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    class Config:
        from_attributes = True

class BidResponse(BaseModel):
    id: int
    order_id: int
    writer_id: int
    amount: float
    delivery_time: Optional[datetime]
    message_to_client: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# Dashboard Schemas
class DashboardStats(BaseModel):
    count: int
    growth: float

class ManagerDashboardResponse(BaseModel):
    active_writers: DashboardStats
    active_orders: DashboardStats
    completion_rate: Dict[str, float]
    avg_response_time: Dict[str, float]
    top_writers: List[WriterResponse]
    urgent_orders: List[OrderResponse]

# Performance Report Schemas
class MonthlyOrder(BaseModel):
    month: str
    orders: int

class WriterPerformance(BaseModel):
    name: str
    orders: int
    rating: float

class OrderBySubject(BaseModel):
    subject: str
    count: int

class Insights(BaseModel):
    order_growth: float
    writer_efficiency: str
    customer_satisfaction: str
    areas_for_improvement: Optional[str] = None

class PerformanceReportResponse(BaseModel):
    monthly_orders: List[MonthlyOrder]
    writer_performance: List[WriterPerformance]
    orders_by_subject: List[OrderBySubject]
    insights: Insights

# Settings Schemas
class NotificationSettings(BaseModel):
    email_notifications: bool
    push_notifications: bool
    weekly_reports: bool

class NotificationSettingsResponse(BaseModel):
    email_notifications: bool
    push_notifications: bool
    weekly_reports: bool

class SystemSettings(BaseModel):
    system_updates: bool
    default_language: str
    default_timezone: str

class SystemSettingsResponse(BaseModel):
    system_updates: bool
    default_language: str
    default_timezone: str

# Admin Path Schemas
class PasswordReset(BaseModel):
    new_password: str

class OrderUpdate(BaseModel):
    type: Optional[str] = None
    service: Optional[str] = None
    subject: Optional[str] = None
    level: Optional[str] = None
    language: Optional[str] = None
    words: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    deadline: Optional[datetime] = None
    styles: Optional[str] = None

class OrderStatusUpdate(BaseModel):
    status: str

class GeneralSettingsUpdate(BaseModel):
    site_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    support_phone: Optional[str] = None
    user_registration: Optional[bool] = None
    system_notifications: Optional[bool] = None
    maintenance_mode: Optional[bool] = None

class EmailSettingsUpdate(BaseModel):
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None

class PaymentSettingsUpdate(BaseModel):
    payment_methods: Optional[Dict[str, bool]] = None
    currency: Optional[Dict[str, str]] = None
    transaction_settings: Optional[Dict[str, float]] = None

class NotificationResponse(BaseModel):
    id: int
    type: str
    message: str
    is_read: bool
    timestamp: datetime
    user_id: int
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

# Submission Schemas
class SubmissionCreate(BaseModel):
    submission_type: SubmissionType
    file_path: Optional[str] = None
    content: Optional[str] = None

    @classmethod
    def validate_submission(cls, values):
        file_path = values.get("file_path")
        content = values.get("content")
        if not file_path and not content:
            raise ValueError("Either file_path or content must be provided")
        return values

class SubmissionResponse(BaseModel):
    id: int
    order_id: int
    writer_id: int
    submission_type: SubmissionType
    file_path: Optional[str]
    content: Optional[str]
    timestamp: datetime
    status: SubmissionStatus
    feedback: Optional[str]

    class Config:
        from_attributes = True

class SubmissionReview(BaseModel):
    status: SubmissionStatus
    feedback: Optional[str] = None

# Order Detail Schema
class OrderDetailResponse(BaseModel):
    id: int
    type: str
    service: str
    subject: str
    level: str
    language: str
    words: int
    title: str
    description: str
    client_id: int
    writer_id: Optional[int]
    price: float
    deadline: datetime
    styles: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    status: str
    response_time: Optional[float]
    selected_bid_id: Optional[int]
    bids: List[BidResponse]
    messages: List[MessageResponse]
    submissions: List[SubmissionResponse]

    class Config:
        from_attributes = True

# New schema for a conversation
class ConversationResponse(BaseModel):
    order_id: int
    order_title: str
    order_status: str
    other_party_username: Optional[str]  # Updated field name
    last_message: Optional[MessageResponse]
    unread_count: int

    class Config:
        from_attributes = True