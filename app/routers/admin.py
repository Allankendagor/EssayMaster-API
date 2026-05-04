from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from typing import List
import json
from datetime import datetime, timezone
from .. import database, schemas, models, utils, oauth2
from ..database import get_db
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/admin", tags=["Admin Portal"])

# Helper function to check if the user is an admin
def check_admin_role(current_user):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized. Admin access required.")
    
# Admin Registration Endpoint
@router.post("/registration", status_code=status.HTTP_201_CREATED, response_model=schemas.UserResponse)
def admin_registration(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check for existing user by email
    existing_admin = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {user.email} already exists. Please use a unique email."
        )

    # Generate a random username (ID) if not provided
    if not user.username:
        while True:
            random_username = utils.generate_random_id()
            if not db.query(models.User).filter(models.User.username == random_username).first():
                break  # Username is unique, exit the loop
    else:
        # Check for existing user by username (if provided)
        existing_username = db.query(models.User).filter(models.User.username == user.username).first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{user.username}' already exists. Please use a unique username."
            )
        random_username = user.username  # Use the provided username

    # Hash the password and prepare user data
    hashed_password = utils.hash(user.password)
    admin_data = {
        "email": user.email,
        "username": random_username,
        "hashed_password": hashed_password,
        "role": "admin",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    new_admin = models.User(**admin_data)

    try:
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create admin user: {str(e)}")

    # Create a profile for the admin
    profile_data = {
        "user_id": new_admin.id,
        "nickname": new_admin.username,
        "short_about": "",
        "long_about": "",
        "created_at": datetime.now(timezone.utc),
        "avatar": None
    }
    new_profile = models.Profile(**profile_data)

    try:
        db.add(new_profile)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create admin profile: {str(e)}")

    # Create a welcome notification for the admin
    notification = models.Notification(
        type="welcome",
        message=f"Welcome to EssayMaster, Admin! Your account has been created. Your username is {random_username}.",
        user_id=new_admin.id,
        timestamp=datetime.now(timezone.utc)
    )

    try:
        db.add(notification)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create welcome notification: {str(e)}")

    return new_admin

# 1. Admin Dashboard
@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    # Total Users
    total_users = db.query(models.User).count()

    # Total Orders
    total_orders = db.query(models.Order).count()

    # Total Revenue
    total_revenue = db.query(models.Order).filter(models.Order.status == "completed").with_entities(
        db.func.sum(models.Order.price)
    ).scalar() or 0

    # Completion Rate
    completed_orders = db.query(models.Order).filter(models.Order.status == "completed").count()
    completion_rate = (completed_orders / total_orders * 100) if total_orders > 0 else 0

    # Recent Activities
    recent_activities = []
    # New user registrations
    new_users = db.query(models.User).order_by(models.User.created_at.desc()).limit(5).all()
    for user in new_users:
        recent_activities.append({
            "type": "new_user",
            "message": f"New user {user.username} registered",
            "timestamp": user.created_at
        })

    # New orders
    new_orders = db.query(models.Order).order_by(models.Order.created_at.desc()).limit(5).all()
    for order in new_orders:
        recent_activities.append({
            "type": "new_order",
            "message": f"Order #{order.id} was created",
            "timestamp": order.created_at
        })

    # Payments
    completed_orders_with_payment = db.query(models.Order).filter(models.Order.status == "completed").order_by(models.Order.updated_at.desc()).limit(5).all()
    for order in completed_orders_with_payment:
        recent_activities.append({
            "type": "payment",
            "message": f"Payment received: ${order.price} for order #{order.id}",
            "timestamp": order.updated_at
        })

    # Completed orders
    completed_orders = db.query(models.Order).filter(models.Order.status == "completed").order_by(models.Order.updated_at.desc()).limit(5).all()
    for order in completed_orders:
        recent_activities.append({
            "type": "order_completed",
            "message": f"Order #{order.id} marked as completed",
            "timestamp": order.updated_at
        })

    # Sort activities by timestamp
    recent_activities.sort(key=lambda x: x["timestamp"], reverse=True)
    recent_activities = recent_activities[:5]  # Limit to 5 activities

    # System Status (this could also be stored in the database if needed)
    system_status = {
        "website": "Operational",
        "api": "Operational",
        "database": "Operational",
        "payment_system": "Operational",
        "file_storage": "Operational"
    }

    return {
        "total_users": total_users,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "completion_rate": completion_rate,
        "recent_activities": recent_activities,
        "system_status": system_status
    }

# 2. User Management
# List all users
@router.get("/users", response_model=List[schemas.UserResponse])
def get_users(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    users = db.query(models.User).all()
    return users

# Add a new user
@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=schemas.UserResponse)
def add_user(user: schemas.UserCreate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {user.email} already exists. Please use a unique email."
        )

    hashed_password = utils.hash(user.password)
    user_data = user.model_dump()
    new_user_data = {
        "email": user_data["email"],
        "username": user_data["username"],
        "hashed_password": hashed_password,
        "role": user_data.get("role", "Customer"),  # Default to Customer if role not specified
        "status": "active",
        "created_at": datetime.utcnow()
    }
    new_user = models.User(**new_user_data)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# Edit a user
@router.put("/users/{user_id}", response_model=schemas.UserResponse)
def edit_user(user_id: int, user_update: schemas.UserUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    update_data = user_update.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["hashed_password"] = utils.hash(update_data.pop("password"))
    for key, value in update_data.items():
        setattr(user, key, value)
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user

# Suspend a user
@router.put("/users/{user_id}/suspend")
def suspend_user(user_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.status = "suspended"
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"User {user.username} has been suspended."}

# Delete a user
@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    db.delete(user)
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT)

# Reset user password
@router.put("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, password_reset: schemas.PasswordReset, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.hashed_password = utils.hash(password_reset.new_password)
    user.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"Password for user {user.username} has been reset."}

# 3. Order Management
# List all orders
@router.get("/orders", response_model=List[schemas.OrderResponse])
def get_orders(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    orders = db.query(models.Order).all()
    return orders

# View order details
@router.get("/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order_details(order_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    return order

# Edit an order
@router.put("/orders/{order_id}", response_model=schemas.OrderResponse)
def edit_order(order_id: int, order_update: schemas.OrderUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    update_data = order_update.model_dump(exclude_unset=True)
    if "deadline_date" in update_data and "deadline_time" in update_data:
        try:
            deadline = datetime.strptime(f"{update_data['deadline_date']} {update_data['deadline_time']}", "%Y-%m-%d %H:%M")
            update_data["deadline"] = deadline
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date or time format.")
        del update_data["deadline_date"]
        del update_data["deadline_time"]

    for key, value in update_data.items():
        setattr(order, key, value)
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order

# Assign a writer to an order
@router.put("/orders/{order_id}/assign-writer")
def assign_writer(order_id: int, writer_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    writer = db.query(models.User).filter(models.User.id == writer_id, models.User.role == "writer").first()
    if not writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    order.writer_id = writer_id
    order.status = "in_progress"
    order.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"Writer {writer.username} assigned to order #{order.id}."}

# Change order status
@router.put("/orders/{order_id}/status")
def change_order_status(order_id: int, status_update: schemas.OrderStatusUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    order.status = status_update.status
    if status_update.status == "completed":
        order.is_active = False
    order.updated_at = datetime.utcnow()
    db.commit()
    return {"message": f"Order #{order.id} status updated to {status_update.status}."}

# Cancel an order
@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(order_id: int, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    order.status = "cancelled"
    order.is_active = False
    order.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT)

# 4. Notifications
# List notifications
@router.get("/notifications", response_model=List[schemas.NotificationResponse])
def get_notifications(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    # Fetch notifications for the admin user
    notifications = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.timestamp.desc()).limit(10).all()

    return notifications

# Mark all notifications as read
@router.put("/notifications/mark-all-read")
def mark_all_notifications_read(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    # Update all unread notifications for the admin user
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).update({"is_read": True})
    db.commit()

    return {"message": "All notifications marked as read."}

# 5. Settings
# Helper function to get or create a setting
def get_or_create_setting(db: Session, key: str, default_value: any):
    setting = db.query(models.Settings).filter(models.Settings.key == key).first()
    if not setting:
        # Convert default_value to string (JSON for complex types)
        value = json.dumps(default_value) if isinstance(default_value, (dict, list)) else str(default_value)
        setting = models.Settings(key=key, value=value)
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting

# Get system settings
@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    # Fetch or initialize settings
    settings = {
        "general": {
            "site_name": get_or_create_setting(db, "site_name", "EssayHub").value,
            "contact_email": get_or_create_setting(db, "contact_email", "admin@essayhub.com").value,
            "support_phone": get_or_create_setting(db, "support_phone", "+1 (555) 123-4567").value,
            "user_registration": json.loads(get_or_create_setting(db, "user_registration", "true").value),
            "system_notifications": json.loads(get_or_create_setting(db, "system_notifications", "true").value),
            "maintenance_mode": json.loads(get_or_create_setting(db, "maintenance_mode", "false").value)
        },
        "email": {
            "smtp_server": get_or_create_setting(db, "smtp_server", "smtp.example.com").value,
            "smtp_port": int(get_or_create_setting(db, "smtp_port", "587").value),
            "smtp_username": get_or_create_setting(db, "smtp_username", "notifications@essayhub.com").value,
            "smtp_password": get_or_create_setting(db, "smtp_password", "********").value,
            "from_email": get_or_create_setting(db, "from_email", "no-reply@essayhub.com").value,
            "from_name": get_or_create_setting(db, "from_name", "EssayHub Support").value
        },
        "payment": {
            "payment_methods": json.loads(get_or_create_setting(db, "payment_methods", {
                "credit_card": False,
                "paypal": False,
                "bank_transfer": False,
                "mobile_money": True
            }).value),
            "currency": json.loads(get_or_create_setting(db, "currency", {
                "symbol": "$",
                "code": "USD"
            }).value),
            "transaction_settings": json.loads(get_or_create_setting(db, "transaction_settings", {
                "minimum_withdrawal_amount": 20.00,
                "writer_commission_rate": 10.00
            }).value)
        }
    }
    return settings

# Update general settings
@router.put("/settings/general")
def update_general_settings(settings: schemas.GeneralSettingsUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    update_data = settings.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setting = db.query(models.Settings).filter(models.Settings.key == key).first()
        if setting:
            setting.value = str(value) if isinstance(value, (str, bool)) else json.dumps(value)
        else:
            setting = models.Settings(key=key, value=str(value) if isinstance(value, (str, bool)) else json.dumps(value))
            db.add(setting)
    db.commit()
    return {"message": "General settings updated successfully.", "settings": update_data}

# Update email settings
@router.put("/settings/email")
def update_email_settings(settings: schemas.EmailSettingsUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    update_data = settings.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setting = db.query(models.Settings).filter(models.Settings.key == key).first()
        if setting:
            setting.value = str(value) if isinstance(value, (str, int)) else json.dumps(value)
        else:
            setting = models.Settings(key=key, value=str(value) if isinstance(value, (str, int)) else json.dumps(value))
            db.add(setting)
    db.commit()
    return {"message": "Email settings updated successfully.", "settings": update_data}

# Update payment settings
@router.put("/settings/payment")
def update_payment_settings(settings: schemas.PaymentSettingsUpdate, db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
    check_admin_role(current_user)

    update_data = settings.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setting = db.query(models.Settings).filter(models.Settings.key == key).first()
        if setting:
            setting.value = json.dumps(value)  # Payment settings are all complex types (dict)
        else:
            setting = models.Settings(key=key, value=json.dumps(value))
            db.add(setting)
    db.commit()
    return {"message": "Payment settings updated successfully.", "settings": update_data}

#viewing order messages 
# View chat history for an order
@router.get("/orders/{order_id}/messages", response_model=List[schemas.MessageResponse])
def view_order_messages(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    # Ensure the user is an admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view messages. Must be an admin."
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