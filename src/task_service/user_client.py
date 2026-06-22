import httpx
import os 
from fastapi import Depends, HTTPException, status
from task_service.auth_wrapper import get_user_id

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8000")

async def get_user_data(user_id: int = Depends(get_user_id)):
    # Ensure timeout is set to avoid hanging requests
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{USER_SERVICE_URL}/v2/users/{user_id}", timeout=5.0)
        except httpx.RequestError as e:
            print(f"Connection error to User Service: {e}")
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "User service unavailable")

    if r.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    response_data = r.json()
    return response_data.get("user", response_data)

async def get_user_email(user_data=Depends(get_user_data)):
    email = user_data.get("email")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User email missing")
    return email
