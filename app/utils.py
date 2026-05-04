from passlib.context import CryptContext
import re
from fastapi import HTTPException

pwd_context=CryptContext(schemes=["bcrypt"],deprecated="auto")


def verify(plain_password, hashed_password):
    return pwd_context.verify(plain_password,hashed_password)

def hash(password:str):

    return pwd_context.hash(password)

#messages checks starts here.

def filter_contact_info(content: str, sender_role: str) -> bool:
    """
    Check if the message contains contact information (email, phone number, or hashed personal number).
    Returns True if the message should be blocked, False otherwise.
    Only applies to writers.
    """
    if sender_role != "writer":
        return False  # Only filter messages sent by writers

    # Define patterns for email, phone number, and hashed personal number
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    phone_pattern = r"(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    # Hashed personal number (e.g., SSN-like patterns or other fixed-length numeric strings)
    hashed_number_pattern = r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9,12}\b"

    # Check for matches
    if re.search(email_pattern, content, re.IGNORECASE):
        return True
    if re.search(phone_pattern, content):
        return True
    if re.search(hashed_number_pattern, content):
        return True

    return False

def block_message(content: str, sender_role: str) -> None:
    """
    Raise an HTTPException if the message contains contact information.
    """
    if filter_contact_info(content, sender_role):
        raise HTTPException(
            status_code=400,
            detail="Message contains contact information (email, phone number, or personal number), which is not allowed."
        )