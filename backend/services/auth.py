"""
Authentication & Authorization Service for FDC Tax CRM

Implements:
- JWT-based authentication
- Role-based access control (RBAC)
- Password hashing with bcrypt
- Token refresh mechanism

Roles:
- admin: Full access to all endpoints
- staff: Access to admin endpoints (white-glove service)
- client: Access to user endpoints only
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging
from enum import Enum

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fdc-tax-crm-secret-key-change-in-production-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 7  # 7 days

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Auth data storage (for roles since DB has limited permissions)
DATA_DIR = Path(__file__).parent.parent / "data"
AUTH_DATA_FILE = DATA_DIR / "auth_roles.json"


# ==================== ENUMS ====================

class UserRole(str, Enum):
    admin = "admin"
    staff = "staff"
    client = "client"
    tax_agent = "tax_agent"  # Read-only in Bookkeeper Tab, can lock for workpapers


# ==================== MODELS ====================

class Token(BaseModel):
    """JWT Token response"""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int  # seconds
    user_id: str
    email: str
    role: str


class TokenData(BaseModel):
    """Data extracted from JWT token"""
    user_id: str
    email: str
    role: str
    exp: Optional[datetime] = None
    token_type: str = "access"  # "access" or "refresh"


class LoginRequest(BaseModel):
    """Login request body"""
    email: str
    password: str


class RegisterRequest(BaseModel):
    """Registration request body"""
    email: str
    password: str
    first_name: str
    last_name: str
    role: str = UserRole.client.value


class ChangePasswordRequest(BaseModel):
    """Change password request"""
    current_password: str
    new_password: str


class AuthUser(BaseModel):
    """Authenticated user context"""
    id: str
    email: str
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True

    def is_admin(self) -> bool:
        return self.role == UserRole.admin.value
    
    def is_staff(self) -> bool:
        return self.role in [UserRole.admin.value, UserRole.staff.value]
    
    def is_client(self) -> bool:
        return self.role == UserRole.client.value


# ==================== AUTH ROLE STORAGE ====================

class AuthRoleStorage:
    """
    File-based storage for user roles.
    Since we can't add columns to the DB, we store roles separately.
    """
    
    def __init__(self, file_path: Path = AUTH_DATA_FILE):
        self.file_path = file_path
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            # Initialize with default roles
            self._save_roles({
                "_default_role": UserRole.client.value,
                "_admin_emails": ["admin@fdctax.com", "admin@example.com"],
                "_staff_emails": ["staff@fdctax.com", "staff@example.com"],
                "users": {}
            })
    
    def _load_roles(self) -> Dict:
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading roles: {e}")
            return {"users": {}}
    
    def _save_roles(self, data: Dict):
        with open(self.file_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def get_user_role(self, user_id: str, email: str) -> str:
        """Get role for a user"""
        data = self._load_roles()
        
        # Check explicit role assignment
        if user_id in data.get("users", {}):
            return data["users"][user_id]
        
        # Check email-based role assignment
        email_lower = email.lower()
        if email_lower in data.get("_admin_emails", []):
            return UserRole.admin.value
        if email_lower in data.get("_staff_emails", []):
            return UserRole.staff.value
        if email_lower in data.get("_tax_agent_emails", []):
            return UserRole.tax_agent.value
        
        # Default role
        return data.get("_default_role", UserRole.client.value)
    
    def set_user_role(self, user_id: str, role: str):
        """Set role for a user"""
        data = self._load_roles()
        if "users" not in data:
            data["users"] = {}
        data["users"][user_id] = role
        self._save_roles(data)
    
    def add_admin_email(self, email: str):
        """Add an email to admin list"""
        data = self._load_roles()
        if "_admin_emails" not in data:
            data["_admin_emails"] = []
        if email.lower() not in data["_admin_emails"]:
            data["_admin_emails"].append(email.lower())
            self._save_roles(data)
    
    def add_staff_email(self, email: str):
        """Add an email to staff list"""
        data = self._load_roles()
        if "_staff_emails" not in data:
            data["_staff_emails"] = []
        if email.lower() not in data["_staff_emails"]:
            data["_staff_emails"].append(email.lower())
            self._save_roles(data)
    
    def add_tax_agent_email(self, email: str):
        """Add an email to tax_agent list"""
        data = self._load_roles()
        if "_tax_agent_emails" not in data:
            data["_tax_agent_emails"] = []
        if email.lower() not in data["_tax_agent_emails"]:
            data["_tax_agent_emails"].append(email.lower())
            self._save_roles(data)
    
    def list_admin_emails(self) -> List[str]:
        data = self._load_roles()
        return data.get("_admin_emails", [])
    
    def list_staff_emails(self) -> List[str]:
        data = self._load_roles()
        return data.get("_staff_emails", [])


# ==================== PASSWORD UTILITIES ====================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


# ==================== JWT UTILITIES ====================

def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT refresh token"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        role = payload.get("role")
        token_type = payload.get("type", "access")
        exp = payload.get("exp")
        
        if not user_id or not email or not role:
            return None
        
        return TokenData(
            user_id=user_id,
            email=email,
            role=role,
            token_type=token_type,
            exp=datetime.fromtimestamp(exp) if exp else None
        )
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None


# ==================== AUTH SERVICE ====================

class AuthService:
    """
    Authentication service for FDC Tax CRM.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.role_storage = AuthRoleStorage()
    
    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user from database by email"""
        query = text("""
            SELECT id, email, password_hash, first_name, last_name, is_active
            FROM public.users 
            WHERE email = :email
        """)
        result = await self.db.execute(query, {"email": email})
        row = result.fetchone()
        
        if not row:
            return None
        
        return {
            "id": str(row.id),
            "email": row.email,
            "password_hash": row.password_hash,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "is_active": row.is_active if row.is_active is not None else True
        }
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user from database by ID"""
        query = text("""
            SELECT id, email, password_hash, first_name, last_name, is_active
            FROM public.users 
            WHERE id = :user_id
        """)
        result = await self.db.execute(query, {"user_id": user_id})
        row = result.fetchone()
        
        if not row:
            return None
        
        return {
            "id": str(row.id),
            "email": row.email,
            "password_hash": row.password_hash,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "is_active": row.is_active if row.is_active is not None else True
        }
    
    async def authenticate_user(self, email: str, password: str) -> Optional[AuthUser]:
        """Authenticate a user with email and password"""
        user = await self.get_user_by_email(email)
        
        if not user:
            logger.warning(f"Login failed: user not found - {email}")
            return None
        
        if not user.get("is_active", True):
            logger.warning(f"Login failed: user inactive - {email}")
            return None
        
        password_hash = user.get("password_hash")
        if not password_hash:
            logger.warning(f"Login failed: no password set - {email}")
            return None
        
        if not verify_password(password, password_hash):
            logger.warning(f"Login failed: invalid password - {email}")
            return None
        
        # Get role - ensure user_id is string
        user_id = str(user["id"])
        role = self.role_storage.get_user_role(user_id, email)
        
        logger.info(f"Login successful: {email} (role: {role})")
        
        return AuthUser(
            id=user_id,
            email=user["email"],
            role=role,
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            is_active=user.get("is_active", True)
        )
    
    async def login(self, email: str, password: str) -> Optional[Token]:
        """Login and return JWT tokens"""
        user = await self.authenticate_user(email, password)
        
        if not user:
            return None
        
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role
        )
        
        refresh_token = create_refresh_token(
            user_id=user.id,
            email=user.email,
            role=user.role
        )
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=user.id,
            email=user.email,
            role=user.role
        )
    
    async def refresh_tokens(self, refresh_token: str) -> Optional[Token]:
        """Refresh access token using refresh token"""
        token_data = decode_token(refresh_token)
        
        if not token_data:
            return None
        
        if token_data.token_type != "refresh":
            logger.warning("Invalid token type for refresh")
            return None
        
        # Verify user still exists and is active
        user = await self.get_user_by_id(token_data.user_id)
        if not user or not user.get("is_active", True):
            return None
        
        # Get current role (may have changed)
        role = self.role_storage.get_user_role(user["id"], user["email"])
        
        # Create new tokens
        new_access_token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            role=role
        )
        
        new_refresh_token = create_refresh_token(
            user_id=user["id"],
            email=user["email"],
            role=role
        )
        
        return Token(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=user["id"],
            email=user["email"],
            role=role
        )
    
    async def register_user(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: str = UserRole.client.value
    ) -> Optional[AuthUser]:
        """Register a new user"""
        # Check if user exists
        existing = await self.get_user_by_email(email)
        if existing:
            raise ValueError("Email already registered")
        
        # Hash password
        password_hash = get_password_hash(password)
        
        # Create user
        user_id = str(uuid.uuid4())
        query = text("""
            INSERT INTO public.users (id, email, password_hash, first_name, last_name, is_active, created_at)
            VALUES (:id, :email, :password_hash, :first_name, :last_name, true, :created_at)
            RETURNING id, email, first_name, last_name
        """)
        
        result = await self.db.execute(query, {
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "first_name": first_name,
            "last_name": last_name,
            "created_at": datetime.now()
        })
        await self.db.commit()
        
        row = result.fetchone()
        if not row:
            return None
        
        # Set role
        self.role_storage.set_user_role(user_id, role)
        
        return AuthUser(
            id=str(row.id),
            email=row.email,
            role=role,
            first_name=row.first_name,
            last_name=row.last_name,
            is_active=True
        )
    
    async def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str
    ) -> bool:
        """Change user's password"""
        user = await self.get_user_by_id(user_id)
        if not user:
            return False
        
        # Verify current password
        if not verify_password(current_password, user.get("password_hash", "")):
            return False
        
        # Update password
        new_hash = get_password_hash(new_password)
        query = text("""
            UPDATE public.users 
            SET password_hash = :password_hash, updated_at = :updated_at
            WHERE id = :user_id
        """)
        
        await self.db.execute(query, {
            "user_id": user_id,
            "password_hash": new_hash,
            "updated_at": datetime.now()
        })
        await self.db.commit()
        
        return True
    
    async def set_user_password(self, user_id: str, new_password: str) -> bool:
        """Admin: Set user's password directly"""
        new_hash = get_password_hash(new_password)
        query = text("""
            UPDATE public.users 
            SET password_hash = :password_hash, updated_at = :updated_at
            WHERE id = :user_id
            RETURNING id
        """)
        
        result = await self.db.execute(query, {
            "user_id": user_id,
            "password_hash": new_hash,
            "updated_at": datetime.now()
        })
        await self.db.commit()
        
        return result.fetchone() is not None
    
    def set_user_role(self, user_id: str, role: str):
        """Set user's role"""
        if role not in [r.value for r in UserRole]:
            raise ValueError(f"Invalid role: {role}")
        self.role_storage.set_user_role(user_id, role)
    
    def get_user_role(self, user_id: str, email: str) -> str:
        """Get user's role"""
        return self.role_storage.get_user_role(user_id, email)


# ==================== SEED TEST USERS ====================

async def seed_test_users(db: AsyncSession):
    """
    Seed test users for development.
    Only creates users if they don't exist.
    """
    auth_service = AuthService(db)
    
    test_users = [
        {
            "email": "admin@fdctax.com",
            "password": "admin123",
            "first_name": "Admin",
            "last_name": "User",
            "role": UserRole.admin.value
        },
        {
            "email": "staff@fdctax.com",
            "password": "staff123",
            "first_name": "Staff",
            "last_name": "User",
            "role": UserRole.staff.value
        },
        {
            "email": "client@example.com",
            "password": "client123",
            "first_name": "Test",
            "last_name": "Client",
            "role": UserRole.client.value
        }
    ]
    
    created = []
    for user_data in test_users:
        existing = await auth_service.get_user_by_email(user_data["email"])
        if not existing:
            try:
                user = await auth_service.register_user(
                    email=user_data["email"],
                    password=user_data["password"],
                    first_name=user_data["first_name"],
                    last_name=user_data["last_name"],
                    role=user_data["role"]
                )
                if user:
                    created.append(user_data["email"])
                    logger.info(f"Created test user: {user_data['email']}")
            except Exception as e:
                logger.warning(f"Could not create test user {user_data['email']}: {e}")
        else:
            # Ensure role is set
            auth_service.role_storage.set_user_role(existing["id"], user_data["role"])
            # Ensure password is set
            if not existing.get("password_hash"):
                await auth_service.set_user_password(existing["id"], user_data["password"])
                logger.info(f"Set password for existing user: {user_data['email']}")
    
    return created
