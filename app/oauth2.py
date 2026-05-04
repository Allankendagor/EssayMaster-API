import jwt
from jose import JWTError, jwt
from datetime import datetime, timedelta,timezone
from . import schemas,database,models
from fastapi import FastAPI, Response, status,Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jwt.exceptions import InvalidTokenError
from .config import settings

Oauth2_scheme=OAuth2PasswordBearer(tokenUrl='login')
#SECRET_KEY
#Algorithm
#Expiration Time
SECRET_KEY=settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

def create_access_token(data:dict):
    to_encode=data.copy()

    expire=datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp":expire})

    encode_jwt=jwt.encode(to_encode,SECRET_KEY,algorithm=ALGORITHM)
    return encode_jwt
 

def verify_access_token(token:str, credentials_exception):
    try:
        payload=jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])
        user_id:str= payload.get("user_id")
        if user_id is None:
          raise credentials_exception
        token_data=schemas.TokenData(id=user_id)

    except JWTError:
        raise credentials_exception
    return token_data

def get_current_user(token:str=Depends(Oauth2_scheme), db:Session=Depends(database.get_db)):
    credentials_exception=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail=f"could not validate credentials", headers={"WWW-Authenticate":"Bearer"},)

    token_data=verify_access_token(token,credentials_exception)
    user_id: int = token_data.id
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user=db.query(models.User).filter(models.User.id==token_data.id).first()

    return user

def get_current_writer(current_user: models.User = Depends(get_current_user)):
    if current_user.role != "writer":
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return current_user

def get_current_client(current_user: models.User = Depends(get_current_user)):
    if current_user.role != "customer":
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return current_user

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return current_user

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if current_user.role != "Manager":
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return current_user

# def get_current_field_officer(current_user: models.User = Depends(get_current_user)):
#    if current_user.role != "Field Officer":
#        raise HTTPException(status_code=400, detail="Not enough permissions")
#    return current_user

#def get_current_farmer(current_user: models.User = Depends(get_current_user)):
#    if current_user.role != "Farmer":
#        raise HTTPException(status_code=400, detail="Not enough permissions")
#    return current_user
