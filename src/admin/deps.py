from fastapi import Depends, HTTPException, status
from user_service.jwtoken import verify_jwt
from user_service.bridge import get_user_repository as _repo

async def get_user_repository():
    return _repo()

async def get_current_user(
    user_id: int = Depends(verify_jwt),
    user_repo = Depends(get_user_repository)
):
    user = await user_repo.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user
