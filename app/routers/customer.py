from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime,timezone
from .. import database, schemas, models, utils, oauth2
from ..database import get_db
from fastapi.responses import JSONResponse
from fastapi import UploadFile, File
import string
import random
from fastapi import WebSocket
from sqlalchemy.sql import and_

router = APIRouter(prefix="/customer", tags=['customer'])

@router.get("/")
def test():
    return {"message": "This is the customer dashboard."}

# Function to generate a random 8-character alphanumeric ID
def generate_random_id(length=8):
    characters = string.ascii_letters + string.digits  # a-z, A-Z, 0-9
    return ''.join(random.choice(characters) for _ in range(length))

# Customer Registration Endpoint
@router.post("/registration", status_code=status.HTTP_201_CREATED, response_model=schemas.UserResponse)
def customer_registration(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check for existing user by email
    existing_customer = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_customer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {user.email} already exists. Please use a unique email."
        )

    # Generate a random username (ID)
    while True:
        random_username = generate_random_id()
        if not db.query(models.User).filter(models.User.username == random_username).first():
            break  # Username is unique, exit the loop

    # Check for existing user by username (in case a username was provided)
    if user.username:
        existing_username = db.query(models.User).filter(models.User.username == user.username).first()
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{user.username}' already exists. Please use a unique username."
            )
        random_username = user.username  # Use the provided username if given

    # Hash the password and prepare user data
    hashed_password = utils.hash(user.password)
    customer_data = {
        "email": user.email,
        "username": random_username,
        "hashed_password": hashed_password,
        "role": "customer"
    }
    new_customer = models.User(**customer_data)
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    # Create a profile for the customer
    profile_data = {
        "user_id": new_customer.id,
        "nickname": new_customer.username,
        "short_about": "",
        "long_about": "",
        "avatar": None
    }
    new_profile = models.Profile(**profile_data)
    db.add(new_profile)
    db.commit()

    # Create a welcome notification for the customer
    notification = models.Notification(
        type="welcome",
        message=f"Welcome to EssayMaster! Your account has been created. Your temporary username is {random_username}. You can change it in your profile.",
        user_id=new_customer.id,
        timestamp=datetime.utcnow()
    )
    db.add(notification)
    db.commit()

    return new_customer

# Update Username Endpoint
@router.put("/profile/update-username", response_model=schemas.UserResponse)
def update_username(
    new_username: str,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    # Verify that the user is a customer
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update username.")

    # Fetch the customer
    customer = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    # Validate the new username
    if len(new_username) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username must be at least 3 characters long.")
    if not new_username.isalnum():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username must contain only letters and numbers.")

    # Check if the new username is already taken
    existing_user = db.query(models.User).filter(models.User.username == new_username).first()
    if existing_user and existing_user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{new_username}' is already taken. Please choose a different username."
        )

    # Update the username
    customer.username = new_username
    customer.updated_at = datetime.utcnow()

    # Update the profile nickname to match the new username
    profile = db.query(models.Profile).filter(models.Profile.user_id == current_user.id).first()
    if profile:
        profile.nickname = new_username

    # Create a notification for the customer
    notification = models.Notification(
        type="username_updated",
        message=f"Your username has been updated to {new_username}.",
        user_id=current_user.id,
        timestamp=datetime.utcnow()
    )
    db.add(notification)

    db.commit()
    db.refresh(customer)

    return customer

# Post a Job as a Customer (Draft Creation)
@router.post("/orders/draft", status_code=status.HTTP_201_CREATED, response_model=schemas.OrderResponse)
def create_order_draft(order: schemas.OrderCreate, db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    print(f"Creating order for user ID: {current_user.id}, Role: {current_user.role}")
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to create jobs.")
    
    # The deadline is now computed in the OrderCreate schema
    db_order = models.Order(
        type=order.type,
        service=order.service,
        subject=order.subject,
        level=order.level,
        language=order.language,
        words=order.words,
        title=order.title,
        description=order.description,
        client_id=current_user.id,
        price=order.price,
        deadline=order.deadline,  # Use the computed deadline
        styles=order.styles,
        created_at=datetime.now(timezone.utc),  # Use offset-aware datetime
        is_active=True
    )
    try:
        db.add(db_order)
        db.commit()
        db.refresh(db_order)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create order draft: {str(e)}")
    
    return db_order

# View All Active Orders for Customer
@router.get("/orders/active", response_model=List[schemas.OrderResponse])
def get_active_orders(db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view orders.")
    
    active_orders = db.query(models.Order).filter(
        models.Order.client_id == current_user.id,
        models.Order.is_active == True
    ).order_by(models.Order.created_at.desc()).all()
    return active_orders

# View All Closed Orders for Customer
@router.get("/orders/closed", response_model=List[schemas.OrderResponse])
def get_closed_orders(db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view orders.")
    
    closed_orders = db.query(models.Order).filter(
        models.Order.client_id == current_user.id,
        models.Order.is_active == False
    ).order_by(models.Order.updated_at.desc()).all()
    return closed_orders

# View All Bids for a Specific Order
@router.get("/orders/{order_id}/bids", response_model=List[schemas.BidResponse])
def view_bids_for_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view bids.")
    
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.client_id == current_user.id
    ).first()
    if not order or not order.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or is no longer active.")
    
    bids = db.query(models.Bid).filter(models.Bid.order_id == order_id).order_by(models.Bid.created_at.desc()).all()
    return bids


# Get details of a specific order (including bids)
@router.get("/orders/{order_id}", response_model=schemas.OrderDetailResponse)
def get_order_details(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    # Ensure the user is a customer
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view orders. Must be a customer."
        )

    # Fetch the order, ensuring it exists, is active, and belongs to the current user
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.client_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not authorized to view it."
        )

    # Filter out the content of blocked messages for non-admins
    if current_user.role != "admin":
        for message in order.messages:
            if message.is_blocked:
                message.content = "[Message blocked due to containing contact information]"

    # Add sender_username to messages in the response
    if order.messages:
        for message in order.messages:
            sender = db.query(models.User).filter(models.User.id == message.sender_id).first()
            message.sender_username = sender.username if sender and sender.username else "Unknown"

    return order

# Endpoint to delete an order
@router.delete("/orders/{order_id}", response_model=schemas.DelMessageResponse)
def delete_order(
    order_id: int,
    db: Session = Depends(database.get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    # Ensure the user is a customer
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete orders. Must be a customer."
        )

    # Fetch the order, ensuring it exists, is active, and belongs to the current user
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.client_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not authorized to delete it."
        )

    # Prevent deletion if the order is completed or has an assigned writer
    if order.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a completed order."
        )

    if order.writer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete an order that has an assigned writer."
        )

    # Perform a soft delete by setting is_active to False
    order.is_active = False
    order.updated_at = datetime.now(timezone.utc)
    db.commit()

    # Optionally, delete related bids and messages
    bids = db.query(models.Bid).filter(models.Bid.order_id == order_id).all()
    for bid in bids:
        db.delete(bid)

    messages = db.query(models.Message).filter(models.Message.order_id == order_id).all()
    for message in messages:
        message.is_blocked = True
        message.updated_at = datetime.now(timezone.utc)

    db.commit()

    return {"detail": "Order deleted successfully"}
# Customer Profile Endpoint
#@router.get("/profile", response_model=schemas.ProfileResponse)
#def get_customer_profile(db: Session = Depends(get_db), current_user: int = Depends(oauth2.get_current_user)):
#    if current_user.role != "Customer":
#        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view profile.")
    
#    profile = db.query(models.Profile).filter(models.Profile.user_id == current_user.id).first()
#    if not profile:
#        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
#    return profile




# app/routers/customer.py (for reference)
@router.get("/profile", response_model=schemas.Profile1)
def profile(
    db: Session = Depends(database.get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    user_profile = db.query(models.User).filter(models.User.id == current_user.id).first()
    
    if not user_profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found!")

    if user_profile.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view profile. Must be a customer."
        )

    orders = db.query(models.Order).filter(models.Order.client_id == current_user.id).all()

    orders_count = len(orders)
    accepted_orders = sum(1 for order in orders if order.status == "completed")
    acceptance_rate = (accepted_orders / orders_count * 100) if orders_count > 0 else 0.0

    paid_orders = sum(1 for order in orders if order.status == "completed")
    pay_rate = (paid_orders / orders_count * 100) if orders_count > 0 else 0.0

    notifications_count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).count()

    orders_history = []
    for order in orders:
        writer_name = "No proposals yet"
        if order.writer_id:
            writer = db.query(models.User).filter(models.User.id == order.writer_id).first()
            writer_name = writer.username if writer and writer.username else "No proposals yet"

        paid_status = False
        if order.status == "completed":
            paid_status = True

        rating = None  # No rating system implemented

        orders_history.append({
            "order_id": order.id,
            "date": order.created_at,
            "status": order.status,
            "writer": writer_name,
            "paid": paid_status,
            "rating": rating
        })

    balance = 0.0

    avatar = None
    if hasattr(user_profile, 'profile') and user_profile.profile and hasattr(user_profile.profile, 'avatar'):
        avatar = user_profile.profile.avatar

    return {
        "user_id": user_profile.id,
        "join_date": user_profile.created_at,
        "balance": balance,
        "notifications_count": notifications_count,
        "orders_count": orders_count,
        "acceptance_rate": acceptance_rate,
        "pay_rate": pay_rate,
        "orders_history": orders_history,
        "email": user_profile.email,
        "role": user_profile.role,
        "avatar": avatar
    }

@router.put("/profile/avatar")
async def upload_avatar(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    # Fetch the user's profile
    profile = db.query(models.Profile).filter(models.Profile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    # Save the file (e.g., to a local directory or cloud storage)
    # For now, this is a placeholder
    file_path = f"uploads/{current_user.id}_{file.filename}"
    # Save the file and get the URL (e.g., using AWS S3 or local storage)
    # For example: file_url = upload_to_s3(file, file_path)

    # Update the avatar field
    profile.avatar = file_path  # Replace with the actual URL after uploading
    db.commit()
    db.refresh(profile)

    return {"message": "Avatar uploaded successfully", "avatar_url": profile.avatar}

#selecting Bid for the customer

@router.put("/orders/{order_id}/select_bid/{bid_id}", response_model=schemas.OrderDetailResponse)
def select_bid(
    order_id: int,
    bid_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    # Ensure the user is a customer
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to select bids. Must be a customer."
        )

    # Fetch the order
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True,
        models.Order.client_id == current_user.id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not authorized to select a bid for it."
        )

    # Ensure the order is in a "pending" state
    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot select a bid for an order that is not in 'pending' status."
        )

    # Fetch the bid
    bid = db.query(models.Bid).filter(
        models.Bid.id == bid_id,
        models.Bid.order_id == order_id
    ).first()

    if not bid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bid not found or does not belong to this order."
        )

    # Update the order with the selected bid
    order.selected_bid_id = bid.id
    order.status = "in_progress"
    order.writer_id = bid.writer_id

    # Create notifications and initial message
    writer_notification = models.Notification(
        type="bid_selected",
        message=f"Congratulations! Your bid of ${bid.amount} on order #{order_id} has been selected. Please start working on the project and communicate with the client via the chat.",
        user_id=bid.writer_id,
        timestamp=datetime.now(timezone.utc)
    )

    customer_notification = models.Notification(
        type="bid_selected",
        message=f"You have selected a bid of ${bid.amount} for order #{order_id}. You can now communicate with the writer via the chat.",
        user_id=current_user.id,
        timestamp=datetime.now(timezone.utc)
    )

    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    admin_notifications = [
        models.Notification(
            type="bid_selected",
            message=f"Customer {current_user.username or 'Unknown'} selected a bid of ${bid.amount} for order #{order_id}.",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc)
        )
        for admin in admin_users
    ]

    initial_message = models.Message(
        order_id=order_id,
        sender_id=current_user.id,
        recipient_id=bid.writer_id,
        content="Hello! I've selected your bid for this order. Let's discuss the project details.",
        timestamp=datetime.now(timezone.utc),
        is_blocked=False
    )

    # Perform all database operations in a single transaction
    try:
        db.add(writer_notification)
        db.add(customer_notification)
        for admin_notification in admin_notifications:
            db.add(admin_notification)
        db.add(initial_message)
        db.commit()
        db.refresh(order)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to select bid or create notifications/message: {str(e)}"
        )

    # Add sender_username to messages in the response
    if order.messages:
        for message in order.messages:
            sender = db.query(models.User).filter(models.User.id == message.sender_id).first()
            message.sender_username = sender.username if sender and sender.username else "Unknown"

    return order

# View Customer Notifications
@router.get("/notifications", response_model=List[schemas.NotificationResponse])
def get_notifications(db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view notifications.")
    
    notifications = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.timestamp.desc()).all()
    return notifications

# Mark Notification as Read
@router.put("/notifications/{notification_id}/read")
def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    if current_user.role != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update notifications.")
    
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id
    ).first()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    
    notification.is_read = True
    db.commit()
    return {"message": "Notification marked as read."}

# WebSocket endpoint for real-time notifications
@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    await websocket.accept()
    try:
        # Validate the token and get the current user
        user = oauth2.get_current_user_from_token(token, db)  # Use the new function
        if user.role != "customer":
            await websocket.close(code=1008)  # Policy violation
            return

        # Keep the WebSocket connection open and send notifications
        while True:
            # Fetch unread notifications for the customer
            notifications = db.query(models.Notification).filter(
                models.Notification.user_id == user.id,
                models.Notification.is_read == False
            ).order_by(models.Notification.timestamp.desc()).all()

            # Send notifications to the client
            await websocket.send_json([{
                "id": n.id,
                "type": n.type,
                "message": n.message,
                "timestamp": n.timestamp.isoformat(),
                "is_read": n.is_read
            } for n in notifications])

            # Wait for a short period before checking again
            await asyncio.sleep(10)  # Check every 10 seconds
    except Exception as e:
        await websocket.close(code=1000)
        print(f"WebSocket error: {str(e)}")


#sending messages to the writer 
# Updated endpoint to fetch writers
@router.get("/writers", response_model=schemas.WritersResponse)
def get_writers(
    db: Session = Depends(database.get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_user)
):
    # Ensure the user is a customer
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view writers. Must be a customer."
        )

    # Fetch all users with role "writer" and status "active"
    writers = db.query(models.User).filter(
        models.User.role == "writer",
        models.User.status == models.UserStatus.active
    ).all()

    # Map writers to the response model
    writers_response = []
    for writer in writers:
        # Fetch the writer's assigned orders
        orders = db.query(models.Order).filter(models.Order.writer_id == writer.id).all()
        orders_count = len(orders)
        completed_orders = sum(1 for order in orders if order.status == "completed")
        success_rate = (completed_orders / orders_count * 100) if orders_count > 0 else 0

        # Use full_name if available, otherwise fallback to username
        name = writer.full_name if writer.full_name else writer.username

        # Use bio as description, or a default if bio is not set
        description = writer.bio if writer.bio else "Professional academic tutor"

        # Use specialization as expertise (split by comma if it's a string like "Business, Nursing")
        expertise = writer.specialization.split(",") if writer.specialization else ["General"]
        expertise = [exp.strip() for exp in expertise if exp.strip()] or ["General"]

        # Format reviews and orders as "XK+" if over 1000
        reviews = f"{orders_count//1000}K+" if orders_count > 1000 else str(orders_count)
        orders_display = f"{orders_count//1000}K+" if orders_count > 1000 else str(orders_count)

        # Determine online status (simplified: assume active writers are online)
        is_online = writer.status == models.UserStatus.active

        # Get avatar from the writer's profile
        avatar = None
        if writer.profile and writer.profile.avatar:
            avatar = writer.profile.avatar

        writers_response.append({
            "id": writer.id,
            "name": name,
            "avatar": avatar,
            "isOnline": is_online,
            "rating": writer.rating if writer.rating > 0 else 5.0,  # Default to 5.0 if no rating
            "reviews": reviews,
            "orders": orders_display,
            "successRate": int(success_rate),
            "description": description,
            "expertise": expertise
        })

    return {"writers": writers_response}

#submission review

@router.put("/orders/{order_id}/review_submission/{submission_id}", response_model=schemas.SubmissionResponse)
def review_submission(
    order_id: int,
    submission_id: int,
    review: schemas.SubmissionReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    # Ensure the user is a customer
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to review submissions. Must be a customer."
        )

    # Fetch the order
    order = db.query(models.Order).filter(models.Order.id == order_id)\
                                  .filter(models.Order.is_active == True)\
                                  .filter(models.Order.client_id == current_user.id)\
                                  .first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found, is not active, or you are not authorized to review submissions for it."
        )

    # Fetch the submission
    submission = db.query(models.Submission).filter(models.Submission.id == submission_id)\
                                            .filter(models.Submission.order_id == order_id)\
                                            .first()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found or does not belong to this order."
        )

    # Ensure the submission is pending review
    if submission.status != schemas.SubmissionStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This submission has already been reviewed."
        )

    # Update the submission with the review
    submission.status = review.status
    submission.feedback = review.feedback

    # Update order status based on the review
    if submission.submission_type == "final":
        if review.status == schemas.SubmissionStatus.accepted:
            order.status = "delivered"  # Order is complete
        elif review.status == schemas.SubmissionStatus.rejected:
            order.status = "in_progress"  # Allow the writer to resubmit
    elif submission.submission_type == "draft":
        if review.status == schemas.SubmissionStatus.rejected:
            order.status = "in_progress"  # Keep working on the order

    try:
        db.commit()
        db.refresh(submission)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to review submission: {str(e)}"
        )

    # Notify the writer
    writer_notification = models.Notification(
        type="submission_reviewed",
        message=f"The client has reviewed your {submission.submission_type} submission for order #{order_id}. Status: {review.status}. Feedback: {review.feedback or 'None'}",
        user_id=submission.writer_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(writer_notification)

    # Add a chat message to notify the writer
    message_content = f"I have reviewed your {submission.submission_type} submission. Status: {review.status}. Feedback: {review.feedback or 'None'}"
    message = models.Message(
        order_id=order_id,
        sender_id=current_user.id,
        recipient_id=submission.writer_id,
        content=message_content,
        timestamp=datetime.now(timezone.utc),
        is_blocked=False
    )
    db.add(message)

    # Notify admins
    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    for admin in admin_users:
        admin_notification = models.Notification(
            type="submission_reviewed",
            message=f"Client {current_user.username} reviewed a {submission.submission_type} submission for order #{order_id}. Status: {review.status}.",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(admin_notification)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create notifications or message: {str(e)}"
        )

    return submission

@router.get("/conversations/", response_model=List[schemas.ConversationResponse])
def get_conversations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    if current_user.role != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view conversations. Must be a customer."
        )

    orders = db.query(models.Order).filter(
        models.Order.client_id == current_user.id
    ).order_by(models.Order.created_at.desc()).all()

    conversations = []
    for order in orders:
        writer_username = None
        if order.writer_id:
            writer = db.query(models.User).filter(models.User.id == order.writer_id).first()
            writer_username = writer.username if writer and writer.username else "Unknown"

        last_message = db.query(models.Message).filter(
            models.Message.order_id == order.id
        ).order_by(models.Message.timestamp.desc()).first()

        unread_count = 0
        if order.writer_id:
            unread_count = db.query(models.Message).filter(
                models.Message.order_id == order.id,
                models.Message.sender_id == order.writer_id,
                models.Message.recipient_id == current_user.id
            ).count()

        if last_message and last_message.is_blocked and current_user.role != "admin":
            last_message.content = "[Message blocked due to containing contact information]"

        conversation = {
            "order_id": order.id,
            "order_title": order.title or "Untitled",
            "order_status": order.status,
            "other_party_username": writer_username,  # Fix: Use other_party_username instead of writer_username
            "last_message": last_message,
            "unread_count": unread_count
        }
        conversations.append(conversation)

    return conversations






@router.get("/directory")
async def directory():
        # if current_user.role != "Customer":
         #  raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Log in as a client.")
         data={
    "services": [
        {
            "value": 1,
            "title": "Writing",
            "is_active": True
        },
        {
            "value": 2,
            "title": "Rewriting",
            "is_active": True
        },
        {
            "value": 3,
            "title": "Editing",
            "is_active": True
        },
        {
            "value": 4,
            "title": "Proofreading",
            "is_active": True
        },
        {
            "value": 5,
            "title": "Problem solving",
            "is_active": True
        },
        {
            "value": 6,
            "title": "Calculations",
            "is_active": True
        }
    ],
    "subjects": [
        {
            "value": 83,
            "title": "Computer science",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": True
        },
        {
            "value": 103,
            "title": "Excel",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": True
        },
        {
            "value": 37,
            "title": "History",
            "is_active": True,
            "subject_group_id": 105,
            "subject_group_title": "History",
            "recent": True
        },
        {
            "value": 138,
            "title": "Data science",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": True
        },
        {
            "value": 141,
            "title": "Emergency management",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": True
        },
        {
            "value": 85,
            "title": "Internet technology (IT)",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": True
        },
        {
            "value": 150,
            "title": "Innovation and Technology",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": True
        },
        {
            "value": 80,
            "title": "Technology",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": True
        },
        {
            "value": 29,
            "title": "Education",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": True
        },
        {
            "value": 118,
            "title": "Programming",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": True
        },
        {
            "value": 1,
            "title": "Art",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 3,
            "title": "Dance",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 139,
            "title": "Design and Modeling",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 5,
            "title": "Drama and Theatre",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 104,
            "title": "Fashion",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 7,
            "title": "Music",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 8,
            "title": "Painting",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 113,
            "title": "Photography",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 6,
            "title": "Visual arts",
            "is_active": True,
            "subject_group_id": 101,
            "subject_group_title": "Arts",
            "recent": False
        },
        {
            "value": 20,
            "title": "Accounting",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 11,
            "title": "Business and Management",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 142,
            "title": "Employee welfare",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 102,
            "title": "Entrepreneurship",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 147,
            "title": "Hospitality management",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 10154,
            "title": "Leadership",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 27,
            "title": "Logistics",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 154,
            "title": "Occupational safety and Health administration",
            "is_active": True,
            "subject_group_id": 104,
            "subject_group_title": "Business and Management",
            "recent": False
        },
        {
            "value": 100,
            "title": "C#",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 99,
            "title": "C++",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 96,
            "title": "Code",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 83,
            "title": "Computer science",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 97,
            "title": "Cryptography",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 137,
            "title": "Cyber security",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 140,
            "title": "Digital science",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 85,
            "title": "Internet technology (IT)",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 109,
            "title": "Java",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 110,
            "title": "Javascript",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 114,
            "title": "PHP",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 118,
            "title": "Programming",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 119,
            "title": "Python",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 158,
            "title": "Software and Applications",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 123,
            "title": "SQL",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 86,
            "title": "Web design",
            "is_active": True,
            "subject_group_id": 106,
            "subject_group_title": "Computer Sciences",
            "recent": False
        },
        {
            "value": 68,
            "title": "Agriculture",
            "is_active": True,
            "subject_group_id": 102,
            "subject_group_title": "Economics",
            "recent": False
        },
        {
            "value": 19,
            "title": "Economics",
            "is_active": True,
            "subject_group_id": 102,
            "subject_group_title": "Economics",
            "recent": False
        },
        {
            "value": 24,
            "title": "Finance",
            "is_active": True,
            "subject_group_id": 102,
            "subject_group_title": "Economics",
            "recent": False
        },
        {
            "value": 26,
            "title": "Investing and Financial markets",
            "is_active": True,
            "subject_group_id": 102,
            "subject_group_title": "Economics",
            "recent": False
        },
        {
            "value": 131,
            "title": "Applications and Forms",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 30,
            "title": "Application writing",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 18,
            "title": "Creative writing",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 29,
            "title": "Education",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 156,
            "title": "Research methods",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 120,
            "title": "Scholarship writing",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 121,
            "title": "Sex education",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 122,
            "title": "Special education",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 160,
            "title": "Study design",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 162,
            "title": "Writing",
            "is_active": True,
            "subject_group_id": 107,
            "subject_group_title": "Education",
            "recent": False
        },
        {
            "value": 2,
            "title": "Architecture",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 82,
            "title": "Aviation",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 34,
            "title": "Engineering",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 150,
            "title": "Innovation and Technology",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 80,
            "title": "Technology",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 125,
            "title": "Telecommunications",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 128,
            "title": "Urban and Environmental planning",
            "is_active": True,
            "subject_group_id": 108,
            "subject_group_title": "Engineering",
            "recent": False
        },
        {
            "value": 52,
            "title": "American literature",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 53,
            "title": "Ancient literature",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 35,
            "title": "English",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 151,
            "title": "Language studies",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 51,
            "title": "Literature",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 56,
            "title": "Shakespeare literature",
            "is_active": True,
            "subject_group_id": 103,
            "subject_group_title": "English and Literature",
            "recent": False
        },
        {
            "value": 94,
            "title": "Anatomy",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 10,
            "title": "Biology",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 101,
            "title": "Dentistry",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 144,
            "title": "Food and Culinary studies",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 62,
            "title": "Healthcare",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 60,
            "title": "Medicine and Health",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 63,
            "title": "Nursing",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 64,
            "title": "Nutrition",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 65,
            "title": "Pharmacology",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 155,
            "title": "Physical education",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 115,
            "title": "Physiology",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 116,
            "title": "Psychiatry",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 66,
            "title": "Sports and Athletics",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 127,
            "title": "Veterinary science",
            "is_active": True,
            "subject_group_id": 118,
            "subject_group_title": "Healthcare and Life Sciences",
            "recent": False
        },
        {
            "value": 39,
            "title": "American history",
            "is_active": True,
            "subject_group_id": 105,
            "subject_group_title": "History",
            "recent": False
        },
        {
            "value": 69,
            "title": "Anthropology",
            "is_active": True,
            "subject_group_id": 105,
            "subject_group_title": "History",
            "recent": False
        },
        {
            "value": 37,
            "title": "History",
            "is_active": True,
            "subject_group_id": 105,
            "subject_group_title": "History",
            "recent": False
        },
        {
            "value": 41,
            "title": "Canadian studies",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 91,
            "title": "Gender studies",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 10155,
            "title": "Globalization",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 149,
            "title": "Information ethics",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 16,
            "title": "Journalism",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 50,
            "title": "Linguistics",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 152,
            "title": "Mythology",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 87,
            "title": "Tourism",
            "is_active": True,
            "subject_group_id": 110,
            "subject_group_title": "Humanities",
            "recent": False
        },
        {
            "value": 10156,
            "title": "Criminal justice",
            "is_active": True,
            "subject_group_id": 109,
            "subject_group_title": "Legal",
            "recent": False
        },
        {
            "value": 48,
            "title": "Criminology",
            "is_active": True,
            "subject_group_id": 109,
            "subject_group_title": "Legal",
            "recent": False
        },
        {
            "value": 106,
            "title": "Forensic science",
            "is_active": True,
            "subject_group_id": 109,
            "subject_group_title": "Legal",
            "recent": False
        },
        {
            "value": 47,
            "title": "Law",
            "is_active": True,
            "subject_group_id": 109,
            "subject_group_title": "Legal",
            "recent": False
        },
        {
            "value": 117,
            "title": "Public administration",
            "is_active": True,
            "subject_group_id": 109,
            "subject_group_title": "Legal",
            "recent": False
        },
        {
            "value": 14,
            "title": "Advertising",
            "is_active": True,
            "subject_group_id": 111,
            "subject_group_title": "Marketing",
            "recent": False
        },
        {
            "value": 58,
            "title": "Marketing",
            "is_active": True,
            "subject_group_id": 111,
            "subject_group_title": "Marketing",
            "recent": False
        },
        {
            "value": 17,
            "title": "Public relations",
            "is_active": True,
            "subject_group_id": 111,
            "subject_group_title": "Marketing",
            "recent": False
        },
        {
            "value": 93,
            "title": "Algebra",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 129,
            "title": "Analytics",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 95,
            "title": "Calculus",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 138,
            "title": "Data science",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 103,
            "title": "Excel",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 107,
            "title": "Geometry",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 59,
            "title": "Mathematics",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 124,
            "title": "Statistics",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 126,
            "title": "Trigonometry",
            "is_active": True,
            "subject_group_id": 112,
            "subject_group_title": "Mathematics and Statistics",
            "recent": False
        },
        {
            "value": 130,
            "title": "Animal science",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 70,
            "title": "Astronomy",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 132,
            "title": "Atmospheric science",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 12,
            "title": "Chemistry",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 71,
            "title": "Environmental science",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 72,
            "title": "Geography",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 73,
            "title": "Geology",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 112,
            "title": "Natural science",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 75,
            "title": "Physics",
            "is_active": True,
            "subject_group_id": 113,
            "subject_group_title": "Natural Sciences",
            "recent": False
        },
        {
            "value": 36,
            "title": "Ethics",
            "is_active": True,
            "subject_group_id": 117,
            "subject_group_title": "Philosophy",
            "recent": False
        },
        {
            "value": 74,
            "title": "Philosophy",
            "is_active": True,
            "subject_group_id": 117,
            "subject_group_title": "Philosophy",
            "recent": False
        },
        {
            "value": 78,
            "title": "Religion and Theology",
            "is_active": True,
            "subject_group_id": 117,
            "subject_group_title": "Philosophy",
            "recent": False
        },
        {
            "value": 141,
            "title": "Emergency management",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 145,
            "title": "Global issues & Disaster and Crisis management",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 146,
            "title": "Global studies",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 148,
            "title": "Immigration and Citizenship",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 25,
            "title": "International affairs / relations",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 111,
            "title": "Military science",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 76,
            "title": "Political science",
            "is_active": True,
            "subject_group_id": 116,
            "subject_group_title": "Political Sciences",
            "recent": False
        },
        {
            "value": 133,
            "title": "Behavioral science and Human development",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 134,
            "title": "Career and Professional development",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 13,
            "title": "Communications and Media",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 135,
            "title": "Community and Society",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 98,
            "title": "Cultural studies",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 143,
            "title": "Family and Child studies",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 105,
            "title": "Feminism",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 108,
            "title": "Human relations",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 77,
            "title": "Psychology",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 157,
            "title": "Social science",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 92,
            "title": "Social work",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 79,
            "title": "Sociology",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        },
        {
            "value": 159,
            "title": "Student activities",
            "is_active": True,
            "subject_group_id": 115,
            "subject_group_title": "Social Sciences",
            "recent": False
        }
    ],
    "types": [
        {
            "value": 1,
            "title": "Essay (any type)",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [
                {
                    "key_field": "style",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 1,
                    "default_id": None
                },
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 3,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 4,
                    "default_id": None
                },
                {
                    "key_field": "sources",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 2,
                    "default_id": 0
                }
            ],
            "popular": 1
        },
        {
            "value": 2,
            "title": "Admission essay",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 45,
            "title": "Analysis (any type)",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 3,
            "title": "Annotated bibliography",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 5,
            "title": "Article review",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 33,
            "title": "Article (written)",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 6,
            "title": "Book/Movie review",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 7,
            "title": "Business plan",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 34,
            "title": "Business proposal",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 8,
            "title": "Case study",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": 6
        },
        {
            "value": 36,
            "title": "Coursework",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 67,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 68,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 65,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 66,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 35,
            "title": "Capstone project",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 10,
            "title": "Creative writing",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 11,
            "title": "Critical thinking",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 37,
            "title": "Discussion post",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": 3
        },
        {
            "value": 38,
            "title": "Lab report",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 39,
            "title": "Letter/Memos",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 19,
            "title": "Literature review",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 41,
            "title": "Outline",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 42,
            "title": "Personal narrative",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 12,
            "title": "Presentation or speech",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [
                {
                    "key_field": "style",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 9,
                    "default_id": None
                },
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 11,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 12,
                    "default_id": None
                },
                {
                    "key_field": "sources",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 10,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 43,
            "title": "Reaction paper",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 20,
            "title": "Reflective writing",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 21,
            "title": "Report",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 13,
            "title": "Research paper",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": 2
        },
        {
            "value": 14,
            "title": "Research proposal",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 51,
            "title": "Systematic review",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 15,
            "title": "Term paper",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 16,
            "title": "Thesis / Dissertation",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 32,
            "title": "PowerPoint presentation",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "slides",
            "fields": [
                {
                    "key_field": "style",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 5,
                    "default_id": None
                },
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 7,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 8,
                    "default_id": None
                },
                {
                    "key_field": "sources",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 6,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 50,
            "title": "PowerPoint presentation with speaker notes",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "slides_with_notes",
            "fields": [
                {
                    "key_field": "style",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 73,
                    "default_id": None
                },
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 75,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 76,
                    "default_id": None
                },
                {
                    "key_field": "sources",
                    "is_visible": True,
                    "is_required": False,
                    "default_value": None,
                    "id": 74,
                    "default_id": 0
                }
            ],
            "popular": 4
        },
        {
            "value": 17,
            "title": "Other",
            "is_active": True,
            "type_group_title": "Assignment",
            "type_group_value": 1,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 22,
            "title": "Homework (any type)",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 35,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 36,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 33,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 34,
                    "default_id": 0
                }
            ],
            "popular": 5
        },
        {
            "value": 23,
            "title": "Biology",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 39,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 40,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 37,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 38,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 24,
            "title": "Chemistry",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 43,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 44,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 41,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 42,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 52,
            "title": "Problems",
            "is_active": False,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "problems",
            "fields": [],
            "popular": None
        },
        {
            "value": 25,
            "title": "Engineering",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 47,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 48,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 45,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 46,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 26,
            "title": "Geography",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 51,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 52,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 49,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 50,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 27,
            "title": "Mathematics",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "problems",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 55,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 56,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 53,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 54,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 28,
            "title": "Physics",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 59,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 60,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 57,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 58,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 29,
            "title": "Statistics",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 63,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 64,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 61,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 62,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 40,
            "title": "Marketing",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 46,
            "title": "Programming",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "tasks",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 15,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 16,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 13,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 14,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 47,
            "title": "Excel",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 19,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 20,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 17,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 18,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 48,
            "title": "Economics",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 23,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 24,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 21,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 22,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 49,
            "title": "Accounting",
            "is_active": True,
            "type_group_title": "Homework",
            "type_group_value": 2,
            "quantity_type_key": "questions",
            "fields": [
                {
                    "key_field": "service",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 27,
                    "default_id": None
                },
                {
                    "key_field": "education_level",
                    "is_visible": True,
                    "is_required": True,
                    "default_value": None,
                    "id": 28,
                    "default_id": None
                },
                {
                    "key_field": "style",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Other",
                    "id": 25,
                    "default_id": 5
                },
                {
                    "key_field": "sources",
                    "is_visible": False,
                    "is_required": False,
                    "default_value": "Any",
                    "id": 26,
                    "default_id": 0
                }
            ],
            "popular": None
        },
        {
            "value": 18,
            "title": "Multiple choice questions",
            "is_active": True,
            "type_group_title": "Questions",
            "type_group_value": 3,
            "quantity_type_key": "questions",
            "fields": [],
            "popular": None
        },
        {
            "value": 31,
            "title": "Short answer questions",
            "is_active": True,
            "type_group_title": "Questions",
            "type_group_value": 3,
            "quantity_type_key": "pages",
            "fields": [],
            "popular": None
        },
        {
            "value": 30,
            "title": "Word problems",
            "is_active": False,
            "type_group_title": "Questions",
            "type_group_value": 3,
            "quantity_type_key": "word_problems",
            "fields": [],
            "popular": None
        }
    ],
    "types_group": [
        {
            "value": 1,
            "title": "Assignment",
            "is_active": True,
            "is_manual_price": False
        },
        {
            "value": 2,
            "title": "Homework",
            "is_active": True,
            "is_manual_price": True
        },
        {
            "value": 3,
            "title": "Questions",
            "is_active": True,
            "is_manual_price": True
        }
    ],
    "styles": [
        {
            "value": 2,
            "title": "APA 6th edition"
        },
        {
            "value": 7,
            "title": "APA 7th edition"
        },
        {
            "value": 10,
            "title": "ASA"
        },
        {
            "value": 9,
            "title": "Bluebook"
        },
        {
            "value": 3,
            "title": "Chicago/Turabian"
        },
        {
            "value": 6,
            "title": "Harvard"
        },
        {
            "value": 8,
            "title": "IEEE"
        },
        {
            "value": 1,
            "title": "MLA"
        },
        {
            "value": 5,
            "title": "Other"
        },
        {
            "value": 4,
            "title": "Not applicable"
        }
    ],
    "languages": [
        {
            "value": 1,
            "title": "English (US)",
            "is_active": True,
            "country": "US"
        },
        {
            "value": 2,
            "title": "English (UK)",
            "is_active": True,
            "country": "GB"
        },
        {
            "value": 3,
            "title": "Spanish (ES)",
            "is_active": True,
            "country": "ES"
        },
        {
            "value": 4,
            "title": "French (FR)",
            "is_active": True,
            "country": "FR"
        }
    ],
    "spaces": [
        {
            "value": 1,
            "title": "Double",
            "is_active": True,
            "words_count": 275
        },
        {
            "value": 2,
            "title": "Single",
            "is_active": True,
            "words_count": 550
        }
    ],
    "academic_degree": [
        {
            "value": 1,
            "title": "Associate",
            "is_active": True
        },
        {
            "value": 2,
            "title": "Bachelor",
            "is_active": True
        },
        {
            "value": 3,
            "title": "Master",
            "is_active": True
        },
        {
            "value": 4,
            "title": "Phd",
            "is_active": True
        }
    ],
    "quantity_types": [
        {
            "value": 0,
            "title": "pages",
            "is_active": True,
            "key": "PAGES"
        },
        {
            "value": 1,
            "title": "slides",
            "is_active": True,
            "key": "SLIDES"
        },
        {
            "value": 2,
            "title": "tasks",
            "is_active": True,
            "key": "TASKS"
        },
        {
            "value": 3,
            "title": "questions",
            "is_active": True,
            "key": "QUESTIONS"
        },
        {
            "value": 4,
            "title": "slides_with_notes",
            "is_active": True,
            "key": "SLIDES_WITH_NOTES"
        },
        {
            "value": 5,
            "title": "problems",
            "is_active": True,
            "key": "PROBLEMS"
        },
        {
            "value": 6,
            "title": "word_problems",
            "is_active": False,
            "key": "WORD_PROBLEMS"
        }
    ],
    "file_settings": {
        "min_size": 1,
        "max_size": 157286400,
        "extensions": {
            "jpg": "image",
            "jpeg": "image",
            "tif": "image",
            "psd": "image",
            "bmp": "image",
            "png": "image",
            "nef": "image",
            "tiff": "image",
            "cr2": "image",
            "dwg": "image",
            "cdr": "image",
            "ai": "image",
            "indd": "image",
            "pin": "image",
            "cdp": "image",
            "skp": "image",
            "stp": "image",
            "3dm": "image",
            "gif": "image",
            "heic": "image",
            "vsdx": "image",
            "e01": "image",
            "compress": "compress",
            "rar": "compress",
            "7z": "compress",
            "lz": "compress",
            "z01": "compress",
            "zip": "compress",
            "tar": "compress",
            "accdb": "compress",
            "pdf": "pdf",
            "xls": "xls",
            "xlsx": "xls",
            "ods": "xls",
            "xlsm": "xls",
            "doc": "doc",
            "docx": "doc",
            "eps": "doc",
            "txt": "doc",
            "odt": "doc",
            "rtf": "doc",
            "pub": "doc",
            "pod": "doc",
            "spv": "doc",
            "sql": "doc",
            "epub": "doc",
            "ppt": "ppt",
            "pptm": "ppt",
            "pptx": "ppt",
            "pps": "ppt",
            "ppsx": "ppt",
            "odp": "ppt",
            "csv": "csv",
            "sav": "csv",
            "pages": "doc",
            "numbers": "xls",
            "keynote": "ppt",
            "avi": "video",
            "mov": "video",
            "mp4": "video",
            "wmv": "video",
            "m4a": "audio",
            "mp3": "audio",
            "wav": "audio",
            "wma": "audio",
            "mmp": "audio"
        }
    },
    "billing_fees": {
        "bank_card": {
            "min_amount": 10,
            "max_amount": 2000,
            "fee": 2.5,
            "mandatory_fee_amount": 4,
            "min_fee_amount": None,
            "max_fee_amount": None
        },
        "payoneer": {
            "min_amount": 20,
            "max_amount": None,
            "fee": None,
            "mandatory_fee_amount": None,
            "min_fee_amount": None,
            "max_fee_amount": None
        },
        "m_pesa": {
            "min_amount": 20,
            "max_amount": 1000,
            "fee": None,
            "mandatory_fee_amount": None,
            "min_fee_amount": None,
            "max_fee_amount": None
        },
        "bank_account": {
            "min_amount": 250,
            "max_amount": None,
            "fee": None,
            "mandatory_fee_amount": None,
            "min_fee_amount": None,
            "max_fee_amount": None
        }
    },
    "levels": [
        {
            "value": 1,
            "title": "High school"
        },
        {
            "value": 4,
            "title": "College"
        },
        {
            "value": 2,
            "title": "Bachelor's"
        },
        {
            "value": 5,
            "title": "Master's"
        },
        {
            "value": 3,
            "title": "Doctorate"
        }
    ],
    "order_file_types": {
        "general": {
            "1": "Draft",
            "0": "Revision",
            "2": "Final",
            "3": "Additional"
        },
        "addons": {
            "4": "AI report",
            "5": "Plagiarism report",
            "6": "Grammar check",
            "7": "1-Page abstract",
            "8": "Printable sources",
            "9": "Detailed outline",
            "10": "Graphics & tables"
        }
    }
}
         return JSONResponse(content=data)
        