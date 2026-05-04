from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
from .. import schemas, models, oauth2
from ..database import get_db
from fastapi import Query

router = APIRouter(prefix="/bids", tags=["Bidding"])

# 1. Writer creates a bid on an order
@router.post("/order/{order_id}/create", response_model=schemas.BidResponse)
def create_bid(
    order_id: int,
    bid: schemas.BidCreate,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_writer),
):
    # Check if the order exists and is active
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.is_active == True).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or closed.")

    # Check if the writer has already placed a bid
    existing_bid = db.query(models.Bid).filter(
        models.Bid.order_id == order_id,
        models.Bid.writer_id == current_user.id
    ).first()
    if existing_bid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already placed a bid on this order.")

    # Validate bid amount
    if bid.amount <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Bid amount must be greater than 0.")

    # Create the bid
    db_bid = models.Bid(order_id=order_id, writer_id=current_user.id, amount=bid.amount)
    db.add(db_bid)
    db.commit()
    db.refresh(db_bid)

    # Create a notification for the admin
    notification = models.Notification(
        type="new_bid",
        message=f"Writer {current_user.username} placed a bid of ${bid.amount} on order #{order_id}",
        user_id=1,  # Assuming admin has user_id 1; adjust this logic as needed
        timestamp=datetime.utcnow()
    )
    db.add(notification)

    # Create a notification for the client
    client_notification = models.Notification(
        type="new_bid",
        message=f"A new bid of ${bid.amount} has been placed on your order #{order_id}",
        user_id=order.client_id,
        timestamp=datetime.utcnow()
    )
    db.add(client_notification)

    db.commit()

    return db_bid

# 2. Client views all bids for their order
@router.get("/order/{order_id}/bids", response_model=List[schemas.BidResponse])
def get_bids_for_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_client)
):
    # Verify that the order exists and belongs to the client
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.client_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or unauthorized access.")

    # Fetch all bids for the order
    bids = db.query(models.Bid).filter(models.Bid.order_id == order_id).all()
    return bids

# 3. Client selects a writer based on bid info
@router.put("/order/{order_id}/select-writer", response_model=schemas.OrderResponse)
def select_writer(
    order_id: int,
    bid_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_client)
):
    # Verify that the order exists and belongs to the client
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.client_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or unauthorized access.")

    # Verify that the bid exists and is associated with the order
    selected_bid = db.query(models.Bid).filter(models.Bid.id == bid_id, models.Bid.order_id == order_id).first()
    if not selected_bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found or unauthorized access.")

    # Fetch the writer associated with the bid
    writer = db.query(models.User).filter(models.User.id == selected_bid.writer_id).first()
    if not writer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Writer not found.")

    # Update the order
    order.is_active = False
    order.writer_id = selected_bid.writer_id  # Use writer_id instead of selected_writer_id
    order.selected_bid_id = selected_bid.id
    order.status = "in_progress"
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)

    # Create a notification for the writer
    writer_notification = models.Notification(
        type="writer_selected",
        message=f"You have been selected for order #{order_id}",
        user_id=writer.id,
        timestamp=datetime.utcnow()
    )
    db.add(writer_notification)

    # Create a notification for the admin
    admin_notification = models.Notification(
        type="writer_selected",
        message=f"Writer {writer.username} has been selected for order #{order_id}",
        user_id=1,  # Assuming admin has user_id 1; adjust this logic as needed
        timestamp=datetime.utcnow()
    )
    db.add(admin_notification)

    db.commit()

    return order

@router.get("/order/{order_id}/bids", response_model=List[schemas.BidResponse])
def get_bids_for_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: schemas.TokenData = Depends(oauth2.get_current_client),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100)
):
    order = db.query(models.Order).filter(models.Order.id == order_id, models.Order.client_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or unauthorized access.")

    bids = db.query(models.Bid).filter(models.Bid.order_id == order_id).offset(skip).limit(limit).all()
    return bids