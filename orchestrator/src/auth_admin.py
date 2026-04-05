"""Firebase Auth Admin helpers for multi-tenancy.

Manages custom claims (orgId, role) on user JWTs,
and signals the frontend to refresh tokens after claims change.
"""

import firebase_admin
from firebase_admin import auth


def _ensure_firebase():
    """Ensure Firebase Admin SDK is initialized."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def set_user_claims(uid: str, org_id: str, role: str) -> None:
    """Set org and role on a user's JWT. Call after any membership change."""
    _ensure_firebase()
    try:
        auth.set_custom_user_claims(uid, {
            "orgId": org_id,
            "role": role,
        })
    except (auth.UserNotFoundError, ValueError):
        pass  # Dev user or invalid uid — skip claims


def get_user_claims(uid: str) -> dict:
    """Read current custom claims for a user."""
    _ensure_firebase()
    try:
        user = auth.get_user(uid)
        return user.custom_claims or {}
    except (auth.UserNotFoundError, ValueError):
        return {}


def signal_token_refresh(db, uid: str) -> None:
    """Write sentinel doc so frontend watcher forces getIdToken(true)."""
    from google.cloud import firestore
    db.collection("users").document(uid).set(
        {"tokenRefreshAt": firestore.SERVER_TIMESTAMP},
        merge=True,
    )
