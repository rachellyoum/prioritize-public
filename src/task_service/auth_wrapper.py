from fastapi import Depends, Request, HTTPException, status
from user_service.jwtoken import verify_jwt

async def extract_token(request: Request):
    # Check Authorization header
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth.split(" ", 1)[1]

    # Fallback to ?token=
    token = request.query_params.get("token")
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing token"
    )

async def get_user_id(token: str = Depends(extract_token)):
    try:
        # verify_jwt returns the user ID directly as an int, not a dict
        user_id = verify_jwt(token)  # This is already an int!
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return user_id  # Just return it, don't try to access ["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {str(e)}"
        )
