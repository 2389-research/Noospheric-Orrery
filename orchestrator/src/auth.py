from __future__ import annotations
"""Firebase Auth middleware for FastAPI.

Validates Firebase ID tokens and extracts user context.
Skips auth when AUTH_REQUIRED=false (local dev) or DB_BACKEND=sqlite.

Usage:
    from .auth import get_current_user, AuthUser

    @router.get("/protected")
    def protected_route(user: AuthUser = Depends(get_current_user)):
        print(user.uid, user.email, user.workspace_id)
"""

import os
from dataclasses import dataclass
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Lazy-init Firebase Admin
_firebase_initialized = False


def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials
        if not firebase_admin._apps:
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        _firebase_initialized = True
    except Exception as e:
        print(f"Firebase Auth init failed: {e}")


@dataclass
class AuthUser:
    uid: str
    email: str | None = None
    name: str | None = None
    workspace_id: str = "default"
    role: str = "editor"  # admin | editor | viewer
    org_id: str = ""


# Dev user for unauthenticated local mode
DEV_USER = AuthUser(uid="dev-user", email="dev@localhost", name="Dev User")

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    """Extract and validate Firebase auth token.

    Returns AuthUser with uid, email, workspace_id, role.
    Skips auth in local dev mode (AUTH_REQUIRED=false or DB_BACKEND=sqlite).
    """
    # Skip auth in local/SQLite mode
    auth_required = os.environ.get("AUTH_REQUIRED", "").lower()
    db_backend = os.environ.get("DB_BACKEND", "sqlite").lower()

    if auth_required == "false" or (db_backend == "sqlite" and auth_required != "true"):
        return DEV_USER

    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = credentials.credentials

    try:
        _init_firebase()
        from firebase_admin import auth
        decoded = auth.verify_id_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Extract custom claims
    uid = decoded.get("uid", "")
    email = decoded.get("email")
    name = decoded.get("name")
    workspace_id = decoded.get("workspace_id", os.environ.get("FIREBASE_WORKSPACE_ID", "default"))
    role = decoded.get("role", "editor")
    org_id = decoded.get("orgId", "")

    return AuthUser(uid=uid, email=email, name=name, workspace_id=workspace_id, role=role, org_id=org_id)


ROLE_HIERARCHY = {"admin": 3, "editor": 2, "viewer": 1}


def require_role(*roles: str):
    """Dependency that checks user has at least one of the specified roles.

    Uses role hierarchy: admin > editor > viewer.
    require_role("viewer") allows admin and editor too.
    require_role("admin") only allows admin.

    Usage:
        @router.post("/admin-only")
        def admin_route(user: AuthUser = Depends(require_role("admin"))):
            ...
    """
    min_level = min(ROLE_HIERARCHY.get(r, 0) for r in roles)

    async def check_role(user: AuthUser = Depends(get_current_user)):
        user_level = ROLE_HIERARCHY.get(user.role, 0)
        if user_level < min_level:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return check_role
