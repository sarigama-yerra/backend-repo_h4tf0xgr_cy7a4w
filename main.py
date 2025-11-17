import os
from datetime import datetime, timedelta
from typing import List, Optional, Literal, Dict

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Leave as LeaveSchema

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utilities
import hashlib

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# Pydantic models for requests
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Literal["student", "faculty", "admin"]
    department: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LeaveApplyRequest(BaseModel):
    reason: str
    type: Literal["sick", "casual", "other"]
    start_date: str  # ISO yyyy-mm-dd
    end_date: str
    attachment_url: Optional[str] = None

class LeaveDecisionRequest(BaseModel):
    status: Literal["approved", "rejected"]
    comment: Optional[str] = None

# Simple auth token storage (for demo only). In real app use JWT.
# We'll issue token = sha256(email+password_hash)

def make_token(email: str, password_hash: str) -> str:
    return hashlib.sha256(f"{email}:{password_hash}".encode()).hexdigest()

# Dependency to get current user from header X-Token
async def get_current_user(x_token: Optional[str] = None) -> Dict:
    from fastapi import Header
    token = await Header(None, alias="X-Token")
    # Note: FastAPI Header dependency can't be used like this in a simple function


# We'll implement a simple helper instead using request headers via dependency injection
from fastapi import Request

async def auth_user(request: Request) -> Dict:
    token = request.headers.get("X-Token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing auth token")
    # find user by recomputing tokens for users
    user = db["user"].find_one({})
    # Inefficient to scan all; better to store token. We'll store token at login into DB for demo
    found = db["user"].find_one({"_token": token})
    if not found:
        raise HTTPException(status_code=401, detail="Invalid token")
    found["id"] = str(found.get("_id"))
    return found

@app.get("/")
def read_root():
    return {"message": "Student Leave Management API"}

@app.post("/auth/register")
def register(payload: RegisterRequest):
    existing = db["user"].find_one({"email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = UserSchema(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
    ).model_dump()
    db["user"].insert_one(doc)
    return {"ok": True}

@app.post("/auth/login")
def login(payload: LoginRequest):
    user = db["user"].find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("password_hash") != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = make_token(user["email"], user["password_hash"]) 
    db["user"].update_one({"_id": user["_id"]}, {"$set": {"_token": token}})
    return {
        "token": token,
        "user": {
            "id": str(user["_id"]),
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "department": user.get("department")
        }
    }

@app.post("/leaves/apply")
async def apply_leave(payload: LeaveApplyRequest, user=Depends(auth_user)):
    # Role: student or faculty can apply
    if user.get("role") not in ["student", "faculty"]:
        raise HTTPException(status_code=403, detail="Only students or faculty can apply leave")
    try:
        start_date = datetime.fromisoformat(payload.start_date).date()
        end_date = datetime.fromisoformat(payload.end_date).date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    leave_doc = LeaveSchema(
        applicant_id=str(user["_id"]),
        applicant_name=user["name"],
        applicant_role=user["role"],
        reason=payload.reason,
        type=payload.type,
        start_date=start_date,
        end_date=end_date,
        attachment_url=payload.attachment_url,
        status="pending",
    ).model_dump()

    inserted_id = db["leave"].insert_one(leave_doc).inserted_id
    return {"ok": True, "id": str(inserted_id)}

@app.get("/leaves/my")
async def my_leaves(user=Depends(auth_user)):
    items = list(db["leave"].find({"applicant_id": str(user["_id"])}).sort("submitted_at", -1))
    for i in items:
        i["id"] = str(i["_id"]) 
        i.pop("_id", None)
    return items

@app.get("/leaves/pending")
async def pending_leaves(user=Depends(auth_user)):
    role = user.get("role")
    if role == "student":
        raise HTTPException(status_code=403, detail="Students cannot view pending approvals")

    # Faculty can approve/reject student leaves only
    # Admin can approve/reject both student and faculty leaves
    query = {"status": "pending"}
    if role == "faculty":
        query["applicant_role"] = "student"
    items = list(db["leave"].find(query).sort("submitted_at", -1))
    for i in items:
        i["id"] = str(i["_id"]) 
        i.pop("_id", None)
    return items

@app.post("/leaves/{leave_id}/decide")
async def decide_leave(leave_id: str, payload: LeaveDecisionRequest, user=Depends(auth_user)):
    role = user.get("role")
    if role not in ["faculty", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    leave = db["leave"].find_one({"_id": ObjectId(leave_id)})
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    if leave["status"] != "pending":
        raise HTTPException(status_code=400, detail="Leave already decided")

    # Permission rules
    if role == "faculty" and leave["applicant_role"] != "student":
        raise HTTPException(status_code=403, detail="Faculty can only decide student leaves")

    update = {
        "status": payload.status,
        "decided_by_id": str(user["_id"]),
        "decided_by_name": user["name"],
        "decided_by_role": role,
        "decision_comment": payload.comment,
        "decided_at": datetime.utcnow()
    }
    db["leave"].update_one({"_id": leave["_id"]}, {"$set": update})
    return {"ok": True}

@app.get("/stats/overview")
async def stats_overview(user=Depends(auth_user)):
    role = user.get("role")
    base_filter = {}
    if role == "student":
        base_filter["applicant_id"] = str(user["_id"])
    elif role == "faculty":
        # Faculty manage student leaves; analytics for student leaves
        base_filter["applicant_role"] = "student"
    # Admin sees everything

    total = db["leave"].count_documents(base_filter)
    pending = db["leave"].count_documents({"status": "pending", **base_filter})
    approved = db["leave"].count_documents({"status": "approved", **base_filter})
    rejected = db["leave"].count_documents({"status": "rejected", **base_filter})

    # approvals by month (last 6 months)
    now = datetime.utcnow()
    from collections import defaultdict
    by_month = defaultdict(int)
    pipeline = [
        {"$match": {**base_filter, "status": {"$in": ["approved", "rejected"]}}},
        {"$group": {"_id": {"y": {"$year": "$decided_at"}, "m": {"$month": "$decided_at"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id.y": 1, "_id.m": 1}}
    ]
    try:
        for row in db["leave"].aggregate(pipeline):
            key = f"{row['_id']['y']}-{row['_id']['m']:02d}"
            by_month[key] = row["count"]
    except Exception:
        pass

    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "by_month": by_month,
    }

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["database_url"] = "✅ Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
