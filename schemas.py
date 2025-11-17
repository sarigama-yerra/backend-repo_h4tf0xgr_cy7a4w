"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Leave -> "leave" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import date, datetime

# Core user schema with role-based access
class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password (SHA256)")
    role: Literal["student", "faculty", "admin"] = Field(..., description="User role")
    department: Optional[str] = Field(None, description="Department or class")
    is_active: bool = Field(True, description="Whether user is active")

class Leave(BaseModel):
    """
    Leave applications collection schema
    Collection name: "leave"
    """
    applicant_id: str = Field(..., description="ID of the applicant user")
    applicant_name: str = Field(..., description="Name of the applicant")
    applicant_role: Literal["student", "faculty"] = Field(..., description="Role of applicant")

    reason: str = Field(..., description="Reason for leave")
    type: Literal["sick", "casual", "other"] = Field(..., description="Type of leave")
    start_date: date = Field(..., description="Start date")
    end_date: date = Field(..., description="End date")
    attachment_url: Optional[str] = Field(None, description="Optional attachment URL")

    status: Literal["pending", "approved", "rejected"] = Field("pending", description="Approval status")
    decided_by_id: Optional[str] = Field(None, description="Approver user id")
    decided_by_name: Optional[str] = Field(None, description="Approver name")
    decided_by_role: Optional[str] = Field(None, description="Approver role")
    decision_comment: Optional[str] = Field(None, description="Optional decision comment")

    submitted_at: datetime = Field(default_factory=datetime.utcnow, description="Submission timestamp")
    decided_at: Optional[datetime] = Field(None, description="Decision timestamp")
