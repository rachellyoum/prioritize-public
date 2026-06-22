"""JWT token creation, verification, and key management."""
from authlib.jose import jwt
from datetime import datetime, timezone
from fastapi import HTTPException
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from pathlib import Path
import os

# ==================== KEY MANAGEMENT ====================

KEYS_DIR = Path("/tmp/jwt_keys") if os.environ.get("CI") else Path("/app/keys")
KEYS_DIR.mkdir(parents=True, exist_ok=True)

PRIVATE_KEY_PATH = KEYS_DIR / "private.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public.pem"

def generate_keys():
    """Auto-generate RSA keys if they don't exist."""
    if PRIVATE_KEY_PATH.exists():
        return
    
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    
    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
    )
    PUBLIC_KEY_PATH.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )

def get_private_key() -> bytes:
    generate_keys()
    return PRIVATE_KEY_PATH.read_bytes()

def get_public_key() -> bytes:
    generate_keys()
    return PUBLIC_KEY_PATH.read_bytes()

# ==================== JWT OPERATIONS ====================

# Store version counter for each user - increments on each login
token_versions = {}

def create_jwt(user_id: int, tier: int, expiry: datetime) -> str:
    """Create RS256 JWT token and invalidate all previous tokens."""
    current_time = datetime.now(timezone.utc)
    
    # Increment version counter for this user
    if user_id not in token_versions:
        token_versions[user_id] = 0
    token_versions[user_id] += 1
    
    header = {'alg': 'RS256'}
    payload = {
        'sub': str(user_id),
        'tier': tier,
        'exp': int(expiry.timestamp()),
        'iat': int(current_time.timestamp()),
        'ver': token_versions[user_id]  # Add version to token
    }
    
    token = jwt.encode(header, payload, get_private_key())
    
    return token.decode('utf-8') if isinstance(token, bytes) else token

def verify_jwt(token: str) -> int:
    """Verify JWT and return user_id."""
    try:
        claims = jwt.decode(token, get_public_key())
        claims.validate()
        
        user_id = int(claims['sub'])
        token_version = claims.get('ver', 0)
        
        # Check if this token version is still valid
        if user_id in token_versions and token_version < token_versions[user_id]:
            raise HTTPException(status_code=401, detail="Token revoked")
        
        return user_id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

def revoke_jwt(token: str):
    """Revoke a token immediately by incrementing version."""
    user_id = verify_jwt(token)
    # Increment version, making this token and all older versions invalid
    if user_id in token_versions:
        token_versions[user_id] += 1
    else:
        token_versions[user_id] = 1

def decode_jwt(token: str) -> dict:
    """Decode JWT and return payload without verification (for rate limiting)."""
    try:
        claims = jwt.decode(token, get_public_key())
        claims.validate()
        return dict(claims)
    except Exception:
        return {}