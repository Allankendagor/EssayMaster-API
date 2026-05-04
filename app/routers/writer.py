from fastapi import APIRouter, Depends, status, HTTPException, Response,UploadFile, File
from sqlalchemy.orm import Session, joinedload
from fastapi.security.oauth2 import OAuth2PasswordRequestForm
from .. import database, schemas, models, utils, oauth2
from ..database import get_db
from typing import List
import shutil  # Added import for file handling
import os
from datetime import datetime,timezone
from fastapi import WebSocket
import asyncio
import logging
from pathlib import Path
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/writer", tags=['writer'])

@router.get("/")
def test():
    return {"message": "This is the writer dashboard."}

# Writer Registration Endpoint
@router.post("/registration", status_code=status.HTTP_201_CREATED, response_model=schemas.UserResponse)
def writer_registration(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check for existing user by username
    if user.username:  # Only check if username is provided
        existing_user = db.query(models.User).filter(models.User.username == user.username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{user.username}' already exists! Please use another username."
            )

    # Check for existing user by email
    existing_email = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user.email}' already exists! Please use another email."
        )

    # Hash the password and prepare user data
    hashed_password = utils.hash(user.password)
    writer_data = {
        "email": user.email,
        "username": user.username,
        "hashed_password": hashed_password,
        "role": "writer",
        "created_at": datetime.now(timezone.utc)
    }
    new_writer = models.User(**writer_data)
    db.add(new_writer)

    # Commit the user to the database to generate the id
    try:
        db.commit()
        db.refresh(new_writer)  # Refresh to get the assigned id
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )

    # Now create the profile with the valid user_id
    nickname = user.username if user.username else f"writer_{new_writer.id}"  # Fallback if username is None
    profile_data = {
        "user_id": new_writer.id,  # new_writer.id is now available
        "nickname": nickname,
        "short_about": "",
        "long_about": "",
        "avatar": None,
        "created_at": datetime.now(timezone.utc)
    }
    new_profile = models.Profile(**profile_data)
    db.add(new_profile)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create profile: {str(e)}"
        )

    return new_writer

# Writer Profile Endpoint
@router.get("/profile", response_model=schemas.WriterProfileResponse)
def get_writer_profile(
    db: Session = Depends(database.get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    # Ensure the user is a writer
    if current_user.role != "writer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this profile. Must be a writer."
        )

    # Fetch user profile with the profile relationship
    user_profile = db.query(models.User).filter(models.User.id == current_user.id).first()
    
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    # Fetch writer's orders
    orders = db.query(models.Order).filter(models.Order.writer_id == current_user.id).all()

    # Calculate statistics
    orders_count = len(orders)
    completed_orders = sum(1 for order in orders if order.status == "completed")
    acceptance_rate = (completed_orders / orders_count * 100) if orders_count > 0 else 0.0
    total_earnings = sum(order.price for order in orders if order.status == "completed")

    # Fetch notifications count
    notifications_count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).count()

    # Prepare order history (only completed orders for the "Completed Orders" tab)
    orders_history = []
    for order in orders:
        if order.status != "completed":
            continue  # Only include completed orders

        # Estimate pages from words (assuming 300 words per page)
        pages = max(1, order.words // 300) if order.words else 1

        orders_history.append({
            "order_id": order.id,
            "title": order.title,
            "date": order.created_at,
            "pages": pages,
            "amount": order.price,
            "rating": order.rating if order.rating is not None else None
        })

    # Safely access avatar
    avatar = None
    if user_profile.profile and hasattr(user_profile.profile, 'avatar'):
        avatar = user_profile.profile.avatar

    # Return the writer profile information
    return {
        "user_id": user_profile.id,
        "join_date": user_profile.created_at,
        "balance": user_profile.balance,  # This could be updated to reflect total_earnings
        "notifications_count": notifications_count,
        "orders_count": orders_count,
        "completed_orders": completed_orders,
        "acceptance_rate": acceptance_rate,
        "total_earnings": total_earnings,
        "orders_history": orders_history,
        "email": user_profile.email,
        "role": user_profile.role,
        "avatar": avatar
    }
# View Active Jobs to Bid On
@router.get("/orders/active", status_code=status.HTTP_200_OK, response_model=List[schemas.OrderResponse])
def view_active_jobs(db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view jobs.")
    
    # Fetch active orders that don't have a selected bid and where the writer hasn't bid
    active_jobs = db.query(models.Order).filter(
        models.Order.is_active == True,
        models.Order.selected_bid_id == None
    ).outerjoin(
        models.Bid, models.Order.id == models.Bid.order_id
    ).filter(
        (models.Bid.writer_id != current_user.id) | (models.Bid.writer_id == None)
    ).options(
        joinedload(models.Order.bids),
        joinedload(models.Order.messages),
        joinedload(models.Order.submissions)
    ).all()

    return active_jobs

# Place a Bid on an Order
@router.post("/orders/{order_id}/bid", status_code=status.HTTP_201_CREATED, response_model=schemas.BidResponse)
def place_bid(
    order_id: int,
    bid_data: schemas.BidCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_writer),
):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to place bids.")

    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.selected_bid_id == None
    ).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found, is no longer active, or already assigned.")

    if bid_data.amount > order.price:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bid amount cannot exceed the order price.")

    if bid_data.delivery_time:
        current_time = datetime.now(timezone.utc)
        # bid_data.delivery_time is now guaranteed to be offset-aware due to the validator
        if bid_data.delivery_time < current_time:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delivery time cannot be in the past.")

        # Ensure order.deadline is offset-aware
        deadline_aware = order.deadline
        if deadline_aware.tzinfo is None:
            deadline_aware = deadline_aware.replace(tzinfo=timezone.utc)

        if bid_data.delivery_time > deadline_aware:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Delivery time cannot be later than the order deadline.")

    existing_bid = db.query(models.Bid).filter(models.Bid.order_id == order_id, models.Bid.writer_id == current_user.id).first()
    if existing_bid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already placed a bid on this order.")

    new_bid = models.Bid(
        order_id=order_id,
        writer_id=current_user.id,
        amount=bid_data.amount,
        delivery_time=bid_data.delivery_time,
        message_to_client=bid_data.message_to_client,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_bid)

    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    if not admin_users:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No admin users found.")

    for admin in admin_users:
        admin_notification = models.Notification(
            type="new_bid",
            message=f"Writer {current_user.username if current_user.username else 'Unknown'} placed a bid of ${bid_data.amount} on order #{order_id}",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(admin_notification)

    client_notification = models.Notification(
        type="new_bid",
        message=f"A new bid of ${bid_data.amount} has been placed on your order #{order_id}",
        user_id=order.client_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(client_notification)

    writer_notification = models.Notification(
        type="bid_placed",
        message=f"You have successfully placed a bid of ${bid_data.amount} on order #{order_id}",
        user_id=current_user.id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(writer_notification)

    try:
        db.commit()
        db.refresh(new_bid)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to place bid or create notifications: {str(e)}")

    return new_bid

# View Writer's Bids
@router.get("/bids", status_code=status.HTTP_200_OK, response_model=List[schemas.BidResponse])
def view_writer_bids(db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view bids.")
    
    writer_bids = db.query(models.Bid).filter(models.Bid.writer_id == current_user.id).options(
        joinedload(models.Bid.order),
        joinedload(models.Bid.writer)
    ).all()
    return writer_bids

# View Assigned Orders
@router.get("/orders/assigned", response_model=List[schemas.OrderResponse])
def view_assigned_orders(db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view assigned orders.")

    # Join Order and Bid to find orders where the writer's bid was selected
    assigned_orders = db.query(models.Order).join(
        models.Bid, models.Order.selected_bid_id == models.Bid.id
    ).filter(
        models.Bid.writer_id == current_user.id
    ).all()
   # Filter out the content of blocked messages for non-admins
    for order in assigned_orders:
        for message in order.messages:
            if message.is_blocked:
                message.content = "[Message blocked due to containing contact information]"

    return assigned_orders

# Upload Completed File
@router.post("/orders/{order_id}/upload", response_model=schemas.OrderResponse)
async def upload_completed_file(
    order_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to upload files.")

    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.writer_id == current_user.id,
        models.Order.is_active == True,
        models.Order.status == "in_progress"  # Ensure order is in a valid state
    ).first()
    
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, not assigned to you, not active, or not in 'in_progress' status."
        )

    allowed_extensions = {".pdf", ".doc", ".docx"}
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type. Only PDF, DOC, and DOCX files are allowed.")

    # Validate file size (e.g., max 10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File size exceeds 10MB limit.")
    await file.seek(0)  # Reset file pointer

    upload_dir = "uploads"
    Path(upload_dir).mkdir(parents=True, exist_ok=True)

    # Generate a safe filename using a UUID
    safe_filename = f"{order_id}_{current_user.id}_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(upload_dir, safe_filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save file: {str(e)}")

    order.file_path = file_path
    order.status = "completed"

    notification = models.Notification(
        type="order_completed",
        message=f"Writer {current_user.username if current_user.username else 'Unknown'} has completed order #{order_id}",
        user_id=order.client_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(notification)

    try:
        db.commit()
        db.refresh(order)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update order or create notification: {str(e)}")

    return order

# Reset Writer Password
@router.put("/password-reset")
def reset_writer_password(
    password_reset: schemas.PasswordReset,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    if current_user.role != "writer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to reset password.")

    writer = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    if len(password_reset.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="New password must be at least 8 characters long.")

    writer.hashed_password = utils.hash(password_reset.new_password)
    writer.updated_at = datetime.now(timezone.utc)

    notification = models.Notification(
        type="password_reset",
        message="Your password has been successfully reset.",
        user_id=current_user.id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(notification)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to reset password: {str(e)}")

    return {"message": "Password has been successfully reset."}


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    await websocket.accept()
    try:
        user = oauth2.get_current_user_from_token(token, db)
        if user.role != "writer":
            await websocket.send_json({"error": "Not authorized: Must be a writer."})
            await websocket.close(code=1008)
            return

        while True:
            # Create a new session for each iteration to avoid session issues
            with database.SessionLocal() as session:
                notifications = session.query(models.Notification).filter(
                    models.Notification.user_id == user.id,
                    models.Notification.is_read == False
                ).order_by(models.Notification.timestamp.desc()).all()

                await websocket.send_json([{
                    "id": n.id,
                    "type": n.type,
                    "message": n.message,
                    "timestamp": n.timestamp.isoformat(),
                    "is_read": n.is_read
                } for n in notifications])

            await asyncio.sleep(10)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await websocket.send_json({"error": f"WebSocket error: {str(e)}"})
        await websocket.close(code=1000)


# Send a message to the client
@router.post("/orders/{order_id}/submit", status_code=status.HTTP_201_CREATED, response_model=schemas.SubmissionResponse)
def submit_work(
    order_id: int,
    submission: schemas.SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_writer)
):
    if current_user.role != "writer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to submit work. Must be a writer."
        )

    order = db.query(models.Order).filter(models.Order.id == order_id)\
                                  .filter(models.Order.is_active == True)\
                                  .filter(models.Order.writer_id == current_user.id)\
                                  .first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not assigned to this order."
        )

    if order.status not in ["in_progress"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit work for an order that is not in 'in_progress' status."
        )

    if not submission.file_path and not submission.content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either a file_path or content must be provided for the submission."
        )

    new_submission = models.Submission(
        order_id=order_id,
        writer_id=current_user.id,
        submission_type=submission.submission_type,
        file_path=submission.file_path,
        content=submission.content,
        timestamp=datetime.now(timezone.utc)
    )

    try:
        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit work: {str(e)}"
        )

    if submission.submission_type == "final":
        order.status = "completed"
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update order status: {str(e)}"
            )

    client_notification = models.Notification(
        type="new_submission",
        message=f"The writer has submitted a {submission.submission_type} for order #{order_id}. Please review the submission.",
        user_id=order.client_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(client_notification)

    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    for admin in admin_users:
        admin_notification = models.Notification(
            type="new_submission",
            message=f"Writer {current_user.username} submitted a {submission.submission_type} for order #{order_id}.",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(admin_notification)

    message = models.Message(
        order_id=order_id,
        sender_id=current_user.id,
        recipient_id=order.client_id,
        content=f"I have submitted a {submission.submission_type} for your review. Please let me know if you have any feedback!",
        timestamp=datetime.now(timezone.utc),
        is_blocked=False
    )
    db.add(message)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notifications or message: {str(e)}"
        )

    return new_submission

#order details
@router.get("/orders/{order_id}", response_model=schemas.OrderDetailResponse)
def get_order_details(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_writer)
):
    if current_user.role != "writer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view orders. Must be a writer."
        )

    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.writer_id == current_user.id
    ).options(
        joinedload(models.Order.bids),
        joinedload(models.Order.messages),
        joinedload(models.Order.submissions)
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not assigned to this order."
        )

    # Let the schema handle serialization, and blocked messages will be filtered in OrderDetailResponse
    return order


# app/routers/writer.py
@router.post("/orders/{order_id}/submit", status_code=status.HTTP_201_CREATED, response_model=schemas.SubmissionResponse)
def submit_work(
    order_id: int,
    submission: schemas.SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_writer)
):
    if current_user.role != "writer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to submit work. Must be a writer."
        )

    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.writer_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not assigned to this order."
        )

    if order.status not in ["in_progress"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit work for an order that is not in 'in_progress' status."
        )

    new_submission = models.Submission(
        order_id=order_id,
        writer_id=current_user.id,
        submission_type=submission.submission_type,
        file_path=submission.file_path,
        content=submission.content,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(new_submission)

    if submission.submission_type == "final":
        order.status = "completed"

    client_notification = models.Notification(
        type="new_submission",
        message=f"The writer has submitted a {submission.submission_type} for order #{order_id}. Please review the submission.",
        user_id=order.client_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(client_notification)

    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    for admin in admin_users:
        admin_notification = models.Notification(
            type="new_submission",
            message=f"Writer {current_user.username if current_user.username else 'Unknown'} submitted a {submission.submission_type} for order #{order_id}.",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(admin_notification)

    message = models.Message(
        order_id=order_id,
        sender_id=current_user.id,
        recipient_id=order.client_id,
        content=f"I have submitted a {submission.submission_type} for your review. Please let me know if you have any feedback!",
        timestamp=datetime.now(timezone.utc),
        is_blocked=False
    )
    db.add(message)

    try:
        db.commit()
        db.refresh(new_submission)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit work, update order, or create notifications/message: {str(e)}"
        )

    return new_submission
