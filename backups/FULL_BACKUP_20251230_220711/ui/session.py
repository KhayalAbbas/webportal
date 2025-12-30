"""
UI session management.

Handles secure session cookies for web UI authentication.
"""

from typing import Optional
from uuid import UUID
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings


class SessionManager:
    """Manages secure session cookies for UI authentication."""
    
    def __init__(self):
        # Use the JWT secret for signing cookies
        self.serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
        self.max_age = 60 * 60 * 8  # 8 hours in seconds
    
    def create_session_token(self, user_id: UUID, tenant_id: UUID, email: str, role: str) -> str:
        """
        Create a signed session token.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            email: User email
            role: User role
            
        Returns:
            Signed token string
        """
        data = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "email": email,
            "role": role,
        }
        return self.serializer.dumps(data)
    
    def verify_session_token(self, token: str) -> Optional[dict]:
        """
        Verify and decode a session token.
        
        Args:
            token: Signed token string
            
        Returns:
            Dict with user_id, tenant_id, email, role if valid, None otherwise
        """
        try:
            data = self.serializer.loads(token, max_age=self.max_age)
            return data
        except (BadSignature, SignatureExpired):
            return None


# Global session manager instance
session_manager = SessionManager()
