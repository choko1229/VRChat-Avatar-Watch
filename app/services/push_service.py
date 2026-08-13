from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlparse

import http_ece
import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.discord import get_setting
from app.models import PushSubscription, User
from app.services.admin_service import save_setting

_VAPID_PRIVATE_KEY_SETTING = "vapid_private_key_pem"
_VAPID_PUBLIC_KEY_SETTING = "vapid_public_key"

# This implements just enough of the Web Push protocol (RFC8291 payload
# encryption + VAPID auth) to POST a notification, using http_ece + py_vapid
# directly instead of the pywebpush package. pywebpush pulls in aiohttp for
# its async API, and aiohttp's compiled extensions crash on import in this
# environment (OPENSSL_Uplink) - unrelated to this app, but avoidable since
# only the synchronous send path is needed here.


def _generate_and_store_vapid_keys(db: Session) -> tuple[str, str]:
    vapid = Vapid()
    vapid.generate_keys()
    private_pem = vapid.private_pem().decode()
    public_key_bytes = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_key_b64url = base64.urlsafe_b64encode(public_key_bytes).rstrip(b"=").decode()
    save_setting(db, _VAPID_PRIVATE_KEY_SETTING, private_pem, True)
    save_setting(db, _VAPID_PUBLIC_KEY_SETTING, public_key_b64url, False)
    return private_pem, public_key_b64url


def get_or_create_vapid_keys(db: Session) -> tuple[str, str]:
    # Auto-provisions a VAPID key pair on first use and stores it in the
    # existing Setting table (masked in the admin UI since is_secret=True) -
    # no separate secrets file or env var for operators to manage, and it
    # survives redeploys the same way every other runtime setting does.
    private_pem = get_setting(db, _VAPID_PRIVATE_KEY_SETTING)
    public_key = get_setting(db, _VAPID_PUBLIC_KEY_SETTING)
    if private_pem and public_key:
        return private_pem, public_key
    return _generate_and_store_vapid_keys(db)


def vapid_public_key(db: Session) -> str:
    return get_or_create_vapid_keys(db)[1]


def vapid_sub(db: Session) -> str:
    # VAPID requires a contact ("sub" claim) as either a mailto: address or
    # an https:// origin. Rather than add a dedicated admin setting, reuse
    # the Discord OAuth redirect URI's origin, which every deployment
    # running notifications already has configured.
    redirect_uri = get_setting(db, "discord_redirect_uri")
    parsed = urlparse(redirect_uri)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "mailto:admin@example.com"


def load_vapid(db: Session) -> Vapid:
    private_pem, _ = get_or_create_vapid_keys(db)
    return Vapid.from_pem(private_pem.encode())


def save_subscription(db: Session, user: User, endpoint: str, p256dh: str, auth: str) -> PushSubscription:
    existing = db.scalar(select(PushSubscription).where(PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint))
    if existing:
        existing.p256dh = p256dh
        existing.auth = auth
        db.commit()
        return existing
    subscription = PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
    db.add(subscription)
    db.commit()
    return subscription


def remove_subscription(db: Session, user: User, endpoint: str) -> None:
    existing = db.scalar(select(PushSubscription).where(PushSubscription.user_id == user.id, PushSubscription.endpoint == endpoint))
    if existing:
        db.delete(existing)
        db.commit()


def has_subscription(db: Session, user: User) -> bool:
    return db.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1)) is not None


def _repad(data: bytes) -> bytes:
    return data + b"===="[: len(data) % 4]


def _encrypt_payload(payload: bytes, p256dh_b64url: str, auth_b64url: str) -> bytes:
    receiver_key = base64.urlsafe_b64decode(_repad(p256dh_b64url.encode()))
    auth_secret = base64.urlsafe_b64decode(_repad(auth_b64url.encode()))
    server_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    return http_ece.encrypt(payload, salt=None, private_key=server_key, dh=receiver_key, auth_secret=auth_secret, version="aes128gcm")


def send_web_push(
    db: Session,
    subscription: PushSubscription,
    title: str,
    body: str,
    url: str = "/me",
    vapid: Vapid | None = None,
    sub: str | None = None,
) -> bool:
    # vapid/sub can be precomputed once and passed in by a caller sending a
    # batch of pushes, instead of each call re-reading the VAPID key and
    # discord_redirect_uri Settings from the DB.
    if vapid is None:
        vapid = load_vapid(db)
    if sub is None:
        sub = vapid_sub(db)
    parsed_endpoint = urlparse(subscription.endpoint)
    vapid_headers = vapid.sign(
        {
            "sub": sub,
            "aud": f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}",
            "exp": int(time.time()) + 12 * 60 * 60,
        }
    )
    payload = json.dumps({"title": title, "body": body, "url": url}).encode()
    try:
        encrypted_body = _encrypt_payload(payload, subscription.p256dh, subscription.auth)
    except Exception:
        return False
    headers = {**vapid_headers, "content-encoding": "aes128gcm", "ttl": "3600"}
    try:
        response = httpx.post(subscription.endpoint, content=encrypted_body, headers=headers, timeout=15)
    except httpx.HTTPError:
        return False
    if response.status_code in (404, 410):
        # Browser/OS revoked this subscription (uninstalled, expired) - stop
        # retrying it on every future notification.
        db.delete(subscription)
        db.commit()
        return False
    return response.status_code < 300
