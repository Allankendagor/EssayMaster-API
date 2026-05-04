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

router = APIRouter(prefix="/messages", tags=["messages"])

@router.post("/{order_id}", status_code=status.HTTP_201_CREATED, response_model=schemas.MessageResponse)
def send_message(
    order_id: int,
    message_data: schemas.MessageCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    # Verify the order exists
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.is_active == True).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or is not active."
        )

    # Determine sender and recipient based on user role
    if current_user.role == "customer":
        if order.client_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to send messages for this order."
            )
        if not order.writer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send a message because no writer is assigned to this order."
            )
        recipient_id = order.writer_id
        recipient_role = "writer"
    elif current_user.role == "writer":
        if order.writer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to send messages for this order."
            )
        if not order.client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send a message because no client is assigned to this order."
            )
        recipient_id = order.client_id
        recipient_role = "customer"
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid role for sending messages."
        )

    # Check for contact information (apply block_message logic)
    is_blocked = utils.block_message(message_data.content, current_user.role)

    # Create the message
    new_message = models.Message(
        order_id=order_id,
        sender_id=current_user.id,
        recipient_id=recipient_id,
        content=message_data.content,
        timestamp=datetime.now(timezone.utc),
        is_blocked=is_blocked
    )
    db.add(new_message)

    # Notify the recipient
    recipient_notification = models.Notification(
        type="new_message",
        message=f"New message from {current_user.username or 'Unknown'} on order #{order_id}: {message_data.content[:50]}...",
        user_id=recipient_id,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(recipient_notification)

    # Notify admins
    admin_users = db.query(models.User).filter(models.User.role == "admin").all()
    for admin in admin_users:
        admin_notification = models.Notification(
            type="new_message",
            message=f"New message from {current_user.role} {current_user.username or 'Unknown'} on order #{order_id}.",
            user_id=admin.id,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(admin_notification)

    try:
        db.commit()
        db.refresh(new_message)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message or create notifications: {str(e)}"
        )

    # Add sender_username for frontend rendering
    new_message.sender_username = current_user.username or "Unknown"

    return new_message

@router.get("/{order_id}", response_model=List[schemas.MessageResponse])
def get_order_messages(
    order_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    # Verify the order exists and is active
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True
    ).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or is not active."
        )

    # Verify user authorization based on role
    if current_user.role == "customer":
        if order.client_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view messages for this order."
            )
    elif current_user.role == "writer":
        if order.writer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view messages for this order."
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid role for viewing messages."
        )

    # Fetch messages for the order with pagination
    messages = db.query(models.Message).filter(
        models.Message.order_id == order_id
    ).order_by(models.Message.timestamp.asc()).offset(skip).limit(limit).all()

    # Enrich messages with sender username and mask blocked messages
    for message in messages:
        sender = db.query(models.User).filter(models.User.id == message.sender_id).first()
        message.sender_username = sender.username if sender and sender.username else "Unknown"
        if message.is_blocked and current_user.role != "admin":
            message.content = "[Message blocked due to containing contact information]"

    return messages

@router.get("/conversations/", response_model=List[schemas.ConversationResponse])
def get_conversations(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    if current_user.role not in ["customer", "writer"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view conversations. Must be a customer or writer."
        )

    if current_user.role == "customer":
        orders = db.query(models.Order).filter(
            models.Order.client_id == current_user.id
        ).order_by(models.Order.created_at.desc()).all()
    else:  # writer
        orders = db.query(models.Order).filter(
            models.Order.writer_id == current_user.id
        ).order_by(models.Order.created_at.desc()).all()

    conversations = []
    for order in orders:
        other_party_username = None
        if current_user.role == "customer" and order.writer_id:
            writer = db.query(models.User).filter(models.User.id == order.writer_id).first()
            other_party_username = writer.username if writer and writer.username else "Unknown"
        elif current_user.role == "writer" and order.client_id:
            client = db.query(models.User).filter(models.User.id == order.client_id).first()
            other_party_username = client.username if client and client.username else "Unknown"

        last_message = db.query(models.Message).filter(
            models.Message.order_id == order.id
        ).order_by(models.Message.timestamp.desc()).first()

        unread_count = 0
        if last_message:
            other_party_id = order.writer_id if current_user.role == "customer" else order.client_id
            if other_party_id:
                unread_count = db.query(models.Message).filter(
                    models.Message.order_id == order.id,
                    models.Message.sender_id == other_party_id,
                    models.Message.recipient_id == current_user.id
                ).count()

            if last_message.is_blocked and current_user.role != "admin":
                last_message.content = "[Message blocked due to containing contact information]"

            if last_message:
                sender = db.query(models.User).filter(models.User.id == last_message.sender_id).first()
                last_message.sender_username = sender.username if sender and sender.username else "Unknown"

        conversation = {
            "order_id": order.id,
            "order_title": order.title or "Untitled",
            "order_status": order.status,
            "other_party_username": other_party_username,
            "last_message": last_message,
            "unread_count": unread_count
        }
        conversations.append(conversation)

    return conversations

# New endpoint to delete a message
@router.delete("/{order_id}/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    order_id: int,
    message_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    # Verify the order exists and is active
    order = db.query(models.Order).filter(
        models.Order.id == order_id,
        models.Order.is_active == True
    ).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or is not active."
        )

    # Verify user authorization to access the order
    if current_user.role == "customer":
        if order.client_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete messages for this order."
            )
    elif current_user.role == "writer":
        if order.writer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete messages for this order."
            )
    elif current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid role for deleting messages."
        )

    # Fetch the message
    message = db.query(models.Message).filter(
        models.Message.id == message_id,
        models.Message.order_id == order_id
    ).first()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found or does not belong to this order."
        )

    # Verify the user is the sender or an admin
    if current_user.role != "admin" and message.sender_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this message. You must be the sender or an admin."
        )

    # Delete the message
    try:
        db.delete(message)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete message: {str(e)}"
        )

    return