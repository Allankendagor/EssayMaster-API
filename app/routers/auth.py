from fastapi import APIRouter, Depends, status, HTTPException, Response
from sqlalchemy.orm import Session  # Fixed import
from fastapi.security.oauth2 import OAuth2PasswordRequestForm
from typing import List
import uuid
from datetime import datetime, timedelta  # Added datetime import
from .. import database, schemas, models, utils, oauth2
from ..database import get_db

router = APIRouter(tags=['Authentication'])


# Login Endpoint
@router.post("/login", response_model=schemas.Token)
def login(user_credentials: schemas.LoginRequest, db: Session = Depends(get_db)):
    # Query the user from the database using email
    user = db.query(models.User).filter(models.User.email == user_credentials.email).first()

    # If the user is not found, raise an HTTP 403 exception
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Credentials"
        )

    # Verify the provided password against the stored hashed password
    if not utils.verify(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Credentials"
        )

    # Create an access token
    access_token = oauth2.create_access_token(data={"user_id": user.id})

    # Return the access token, its type, and the user's role
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

# Logout Endpoint
@router.post("/logout")
def logout(db: Session = Depends(get_db), current_user: schemas.TokenData = Depends(oauth2.get_current_user)):
    # In a real app, you might invalidate the token here (e.g., by adding it to a blacklist)
    response_data = {
        "data": {},
        "success": True
    }
    return response_data

# Request a Password Reset
@router.post("/password-reset/request")
def request_password_reset(email: str, db: Session = Depends(get_db)):
    # Find the user by email (no role restriction)
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User with this email not found.")

    # Generate a reset token
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=1)  # Token expires in 1 hour

    # Store the token in the database
    reset_token = models.PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at,
        used=False
    )
    db.add(reset_token)
    db.commit()

    # In a real app, send the token via email
    print(f"Password reset token for {email}: {token}")  # Mock email sending

    return {"message": "Password reset token has been sent to your email."}

# Confirm Password Reset with Token
@router.post("/password-reset/confirm")
def confirm_password_reset(
    token: str,
    password_reset: schemas.PasswordReset,
    db: Session = Depends(get_db)
):
    # Find the reset token
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()

    if not reset_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")

    # Find the user (no role restriction)
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Validate the new password
    if len(password_reset.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="New password must be at least 8 characters long.")

    # Update the password
    user.hashed_password = utils.hash(password_reset.new_password)
    user.updated_at = datetime.utcnow()

    # Mark the token as used
    reset_token.used = True

    # Create a notification for the user
    notification = models.Notification(
        type="password_reset",
        message="Your password has been successfully reset.",
        user_id=user.id,
        timestamp=datetime.utcnow()
    )
    db.add(notification)

    db.commit()

    return {"message": "Password has been successfully reset."}