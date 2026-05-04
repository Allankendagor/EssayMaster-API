from fastapi import FastAPI, Response, status, HTTPException,Depends,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from fastapi.params import Body
from pydantic import BaseModel
from random import randrange
from psycopg2.extras import RealDictCursor
from sqlalchemy.orm import session
from . import models,schemas
from .database import engine, sessionLocal,get_db
#from .routers import post,user,auth,vote
from .routers import auth,customer,writer,admin,manager,Bidding,messages
from .config import settings
import os
from dotenv import load_dotenv
from mangum import Mangum

models.Base.metadata.create_all(bind=engine)

app=FastAPI()
handler=Mangum(app)
load_dotenv()


origins=["http://localhost:3000", "http://127.0.0.1:3000","http://localhost:8080","http://192.168.197.1:8080"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Handle both HTTP and HTTPS traffic without redirects
@app.middleware("http")
async def handle_http_https(request, call_next):
    # No redirect logic; both HTTP and HTTPS requests are allowed
    response = await call_next(request)
    return response

app.include_router(auth.router)
app.include_router(customer.router)
app.include_router(writer.router)
app.include_router(manager.router)
app.include_router(admin.router)
app.include_router(Bidding.router)
app.include_router(messages.router)
#app.include_router(health.router)
@app.get("/")
async def root():    
         print(os.getenv('DATABASE_HOSTNAME'))

         return {"message": "welcome to EssayMaster API and bidding system."}


       