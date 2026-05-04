from fastapi import APIRouter, Depends, status, HTTPException, Response, FastAPI
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime, timedelta
from .. import database, schemas, models, utils, oauth2
from ..database import get_db

router = APIRouter(prefix="/manager", tags=['manager'])

# Manager Dashboard
@router.get("/dashboard", response_model=schemas.ManagerDashboardResponse)
def get_dashboard(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access manager dashboard.")

    # Active Writers
    active_writers = db.query(models.User).filter(models.User.role == "Writer", models.User.status == "active").count()
    last_week_writers = db.query(models.User).filter(
        models.User.role == "Writer",
        models.User.status == "active",
        models.User.created_at >= datetime.utcnow() - timedelta(days=7)
    ).count()
    writer_growth = ((active_writers - last_week_writers) / last_week_writers * 100) if last_week_writers else 0

    # Active Orders
    active_orders = db.query(models.Order).filter(models.Order.is_active == True).count()
    last_week_orders = db.query(models.Order).filter(
        models.Order.is_active == True,
        models.Order.created_at >= datetime.utcnow() - timedelta(days=7)
    ).count()
    order_growth = ((active_orders - last_week_orders) / last_week_orders * 100) if last_week_orders else 0

    # Completion Rate
    total_orders = db.query(models.Order).count()
    completed_orders = db.query(models.Order).filter(models.Order.status == "completed").count()
    completion_rate = (completed_orders / total_orders * 100) if total_orders else 0
    last_month_completed = db.query(models.Order).filter(
        models.Order.status == "completed",
        models.Order.updated_at >= datetime.utcnow() - timedelta(days=30)
    ).count()
    last_month_total = db.query(models.Order).filter(
        models.Order.updated_at >= datetime.utcnow() - timedelta(days=30)
    ).count()
    last_month_rate = (last_month_completed / last_month_total * 100) if last_month_total else 0
    completion_growth = completion_rate - last_month_rate

    # Average Response Time
    response_times = db.query(models.Order).filter(models.Order.response_time != None).all()
    avg_response_time = sum([order.response_time for order in response_times]) / len(response_times) if response_times else 0
    last_week_response = db.query(models.Order).filter(
        models.Order.response_time != None,
        models.Order.created_at >= datetime.utcnow() - timedelta(days=7)
    ).all()
    last_week_avg = sum([order.response_time for order in last_week_response]) / len(last_week_response) if last_week_response else 0
    response_time_change = avg_response_time - last_week_avg

    # Top Performing Writers
    top_writers = db.query(models.User).filter(models.User.role == "Writer", models.User.status == "active").order_by(models.User.rating.desc()).limit(4).all()

    # Urgent Orders
    urgent_orders = db.query(models.Order).filter(
        models.Order.is_active == True,
        models.Order.deadline <= datetime.utcnow() + timedelta(days=2)
    ).order_by(models.Order.deadline.asc()).limit(5).all()

    return {
        "active_writers": {"count": active_writers, "growth": writer_growth},
        "active_orders": {"count": active_orders, "growth": order_growth},
        "completion_rate": {"rate": completion_rate, "growth": completion_growth},
        "avg_response_time": {"time": avg_response_time, "change": response_time_change},
        "top_writers": top_writers,
        "urgent_orders": urgent_orders
    }

# Writer Management - List Writers
@router.get("/writers", response_model=List[schemas.WriterResponse])
def get_writers(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to manage writers.")

    writers = db.query(models.User).filter(models.User.role == "Writer").all()
    return writers

# Add New Writer
@router.post("/writers", status_code=status.HTTP_201_CREATED, response_model=schemas.WriterResponse)
def add_writer(writer: schemas.WriterCreate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to add writers.")

    existing_writer = db.query(models.User).filter(models.User.email == writer.email).first()
    if existing_writer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Writer with email {writer.email} already exists."
        )

    hashed_password = utils.hash(writer.password)
    writer_data = {
        "email": writer.email,
        "username": writer.full_name,
        "hashed_password": hashed_password,
        "role": "Writer",
        "full_name": writer.full_name,
        "phone_number": writer.phone_number,
        "specialization": writer.specialization,
        "education_background": writer.education_background,
        "work_experience": writer.work_experience,
        "bio": writer.bio,
        "status": "active",
        "created_at": datetime.utcnow()
    }
    new_writer = models.User(**writer_data)
    db.add(new_writer)
    db.commit()
    db.refresh(new_writer)
    return new_writer

# Writer Profile
@router.get("/writers/{writer_id}", response_model=schemas.WriterProfileResponse)
def get_writer_profile(writer_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view writer profiles.")

    writer = db.query(models.User).filter(models.User.id == writer_id, models.User.role == "Writer").first()
    if not writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    pending_works = db.query(models.Order).filter(models.Order.writer_id == writer_id, models.Order.status == "in_progress").all()
    completed_works = db.query(models.Order).filter(models.Order.writer_id == writer_id, models.Order.status == "completed").all()

    return {
        "writer": writer,
        "pending_works": pending_works,
        "completed_works": completed_works
    }

# Update Writer Details
@router.put("/writers/{writer_id}", response_model=schemas.WriterResponse)
def update_writer(writer_id: int, writer: schemas.WriterUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update writers.")

    db_writer = db.query(models.User).filter(models.User.id == writer_id, models.User.role == "Writer").first()
    if not db_writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    update_data = writer.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_writer, key, value)
    db.commit()
    db.refresh(db_writer)
    return db_writer

# Suspend Writer
@router.patch("/writers/{writer_id}/suspend", response_model=schemas.WriterResponse)
def suspend_writer(writer_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to suspend writers.")

    writer = db.query(models.User).filter(models.User.id == writer_id, models.User.role == "Writer").first()
    if not writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    writer.status = "suspended"
    db.commit()
    db.refresh(writer)
    return writer

# Performance Reports
@router.get("/reports", response_model=schemas.PerformanceReportResponse)
def get_performance_reports(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view reports.")

    # Monthly Orders
    monthly_orders = []
    for month in range(1, 7):  # Last 6 months
        start_date = datetime.utcnow() - timedelta(days=30 * (6 - month))
        end_date = start_date + timedelta(days=30)
        count = db.query(models.Order).filter(
            models.Order.created_at >= start_date,
            models.Order.created_at < end_date
        ).count()
        monthly_orders.append({"month": start_date.strftime("%b"), "orders": count})

    # Writer Performance (Ratings)
    top_writers = db.query(models.User).filter(models.User.role == "Writer").order_by(models.User.rating.desc()).limit(5).all()
    writer_performance = []
    for writer in top_writers:
        ratings = db.query(models.Order).filter(models.Order.writer_id == writer.id).all()
        writer_performance.append({
            "name": writer.full_name,
            "orders": len(ratings),
            "rating": writer.rating
        })

    # Orders by Subject
    subjects = db.query(models.Order.subject, func.count(models.Order.id)).group_by(models.Order.subject).all()
    orders_by_subject = [{"subject": subject, "count": count} for subject, count in subjects]

    # Key Insights (Simplified)
    total_orders = db.query(models.Order).count()
    last_quarter_orders = db.query(models.Order).filter(
        models.Order.created_at >= datetime.utcnow() - timedelta(days=90)
    ).count()
    order_growth = ((total_orders - last_quarter_orders) / last_quarter_orders * 100) if last_quarter_orders else 0

    return {
        "monthly_orders": monthly_orders,
        "writer_performance": writer_performance,
        "orders_by_subject": orders_by_subject,
        "insights": {
            "order_growth": order_growth,
            "writer_efficiency": "15% faster",  # Placeholder
            "customer_satisfaction": "94%"  # Placeholder
        }
    }

# Settings - Update Profile
@router.put("/settings/profile", response_model=schemas.UserResponse)
def update_profile(profile: schemas.UserUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update profile.")

    db_user = db.query(models.User).filter(models.User.id == current_user.id).first()
    update_data = profile.dict(exclude_unset=True)
    if "password" in update_data:
        update_data["hashed_password"] = utils.hash(update_data.pop("password"))
    for key, value in update_data.items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user

# Settings - Update Notifications
@router.put("/settings/notifications", response_model=schemas.NotificationSettingsResponse)
def update_notifications(settings: schemas.NotificationSettings, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update settings.")

    db_user = db.query(models.User).filter(models.User.id == current_user.id).first()
    db_user.email_notifications = settings.email_notifications
    db_user.push_notifications = settings.push_notifications
    db_user.weekly_reports = settings.weekly_reports
    db.commit()
    db.refresh(db_user)
    return {
        "email_notifications": db_user.email_notifications,
        "push_notifications": db_user.push_notifications,
        "weekly_reports": db_user.weekly_reports
    }

# Settings - Update System
@router.put("/settings/system", response_model=schemas.SystemSettingsResponse)
def update_system(settings: schemas.SystemSettings, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update system settings.")

    # In a real app, system settings might be stored in a separate table or config file
    # For simplicity, we'll assume they're stored in a settings table or as user preferences
    db_user = db.query(models.User).filter(models.User.id == current_user.id).first()
    db_user.system_updates = settings.system_updates
    db_user.default_language = settings.default_language
    db_user.default_timezone = settings.default_timezone
    db.commit()
    db.refresh(db_user)
    return {
        "system_updates": db_user.system_updates,
        "default_language": db_user.default_language,
        "default_timezone": db_user.default_timezone
    }

# View chat history for an order
@router.get("/orders/{order_id}/messages", response_model=List[schemas.MessageResponse])
def view_order_messages(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    # Ensure the user is an manager
    if current_user.role != "Manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view messages. Must be an Manager."
        )

    # Fetch the order to ensure it exists
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found."
        )

    # Fetch all messages for the order
    messages = db.query(models.Message).filter(models.Message.order_id == order_id).all()
    return messages