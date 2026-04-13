from __future__ import annotations
"""Auth middleware for FastAPI.

Local mode: always returns DEV_USER (no external auth required).
The AuthUser dataclass and role hierarchy are preserved for future
auth backends (e.g., simple JWT, OAuth).

Usage:
    from .auth import get_current_user, AuthUser

    @router.get("/protected")
    def protected_route(user: AuthUser = Depends(get_current_user)):
        print(user.uid, user.email, user.workspace_id)
"""

from dataclasses import dataclass
from fastapi import Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


@dataclass
class AuthUser:
    uid: str
    email: str | None = None
    name: str | None = None
    workspace_id: str = "default"
    role: str = "editor"  # admin | editor | viewer
    org_id: str = ""


# Dev user for local mode
DEV_USER = AuthUser(uid="dev-user", email="dev@localhost", name="Dev User", role="admin")

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthUser:
    """Return the current user. Always returns DEV_USER in local mode."""
    return DEV_USER


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
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return check_role
