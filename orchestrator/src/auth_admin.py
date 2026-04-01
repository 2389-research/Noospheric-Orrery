"""Firebase Auth Admin helpers for multi-tenancy.

Manages custom claims (orgId, role) on user JWTs,
and signals the frontend to refresh tokens after claims change.
"""

from firebase_admin import auth


def set_user_claims(uid: str, org_id: str, role: str) -> None:
    """Set org and role on a user's JWT. Call after any membership change."""
    auth.set_custom_user_claims(uid, {
        "orgId": org_id,
        "role": role,
    })


def get_user_claims(uid: str) -> dict:
    """Read current custom claims for a user."""
    user = auth.get_user(uid)
    return user.custom_claims or {}


def signal_token_refresh(db, uid: str) -> None:
    """Write sentinel doc so frontend watcher forces getIdToken(true)."""
    from google.cloud import firestore
    db.collection("users").document(uid).set(
        {"tokenRefreshAt": firestore.SERVER_TIMESTAMP},
        merge=True,
    )
