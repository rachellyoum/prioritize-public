from fastapi import FastAPI, Depends, Response, HTTPException, UploadFile, File, Form, Security, Query
from sqlalchemy.exc import IntegrityError
import bcrypt
import logging
from typing import Literal, Optional
from .models.user import (
    UserRepository, 
    get_user_repository, 
    ScheduleRepository, 
    get_schedule_repository,
    FriendshipRepository, 
    get_friendship_repository,
    User 
)
from sqlalchemy import update, select
from fastapi.responses import FileResponse
from user_service.avatar import save_avatar, delete_avatar, get_avatar_path, avatar_exists
from user_service.jwtoken import create_jwt, revoke_jwt, verify_jwt
from datetime import datetime, timedelta, timezone
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import inspect
from event_service.routes import router as events_router
from event_service.analytics import router as analytics_router
from scheduler_service.api import router as scheduler_router
from study_timer.study_timer_api import router as study_timer_router
from admin.main import ui
from scheduler_service.calendar_api import router as calendar_router
from task_service.api import router as task_router

from fastapi.staticfiles import StaticFiles

from scheduler_service.models import GeneratedSchedule
from task_service.models import Task

from .schemas import (
    UserSchema, 
    UserCreateSchema, 
    UserUpdateSchema, 
    UserDeleteSchema,
    FriendRequestCreateSchema, 
    FriendRequestSchema,
    AuthenticationCreateSchema,
    AuthenticationResponseSchema,
    AuthenticationDeleteSchema,
    ScheduleEntryCreate,
    ScheduleEntryOut,
    FindCommonTimeRequest,
)

bearer_scheme = HTTPBearer(auto_error=False)

logger = logging.getLogger('uvicorn.error')
app = FastAPI()
app.include_router(events_router)
app.include_router(analytics_router)
app.include_router(scheduler_router)
app.include_router(study_timer_router)
app.include_router(calendar_router)
app.include_router(task_router)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    
    Args:
        plain_password: The plain text password to verify
        hashed_password: The hashed password to compare against
        
    Returns:
        bool: True if the passwords match, False otherwise
    """
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode()
    return bcrypt.checkpw(plain_password.encode(), hashed_password)


@app.post("/users/", status_code=201, include_in_schema=False) 
async def create_user(user: UserCreateSchema, response: Response, user_repo: UserRepository = Depends(get_user_repository)): 
    """
    Create a new user with email and password.
    
    Args:
        user: UserCreateSchema containing name, email, and password
        response: FastAPI Response object for setting status codes
        user_repo: UserRepository dependency injection
        
    Returns:
        dict: Created user information (excludes password)
        
    Raises:
        409 Conflict: If username or email already exists
    """
    try:
        # Create user with hashed password
        new_user = await user_repo.create(user.name, user.email, user.password, user.timezone)
        return {"user": UserSchema.from_db_model(new_user)}
    except IntegrityError:
        _sess = getattr(user_repo, "session", None) or getattr(user_repo, "db", None)
        if _sess is not None:
            _sess.rollback()
        raise HTTPException(status_code=409, detail="User with this name or email already exists")

@app.get("/users/", include_in_schema=False) 
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    """
    Retrieve all users from the database.
    
    Args:
        user_repo: UserRepository dependency injection
        
    Returns:
        dict: List of all users (excludes passwords)
    """
    # Get all user models from database
    user_models = await user_repo.get_all()
    # Convert database models to schema objects
    users = []
    for model in user_models:
        users.append(UserSchema.from_db_model(model))
    return {'users': users}

@app.get("/users/{name}", include_in_schema=False) 
async def get_user(name: str, user_repo: UserRepository = Depends(get_user_repository)):
    """
    Retrieve a specific user by username.
    
    Args:
        name: Username to search for
        user_repo: UserRepository dependency injection
        
    Returns:
        dict: User information if found

    Raises:
        404 Not Found: If user doesn't exist
    """
    user = await user_repo.get_by_name(name)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": UserSchema.from_db_model(user).model_dump()} #used to expose the hashed pw: SECURITY ISSUE. fixed by using UserSchema


# Allow users to delete without admin 
@app.post("/users/{name}/delete", status_code=204, include_in_schema=False) 
async def delete_user(
    name: str, 
    body: UserDeleteSchema, 
    user_repo: UserRepository = Depends(get_user_repository)
):

    """
    Delete a user by username and password.

    Args: 
        name: Username of the user to delete
    
    Returns:
        Response: HTTP 204 No Content on successful deletion
    """
    user = await user_repo.get_by_name(name)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    await user_repo.delete(name)
    return Response(status_code=204)

# ==================== FRIEND REQUEST ROUTES ====================

@app.post("/users/{user_id}/friend-requests/", status_code=201, include_in_schema=False)
async def send_friend_request(
    user_id: int,
    request_data: FriendRequestCreateSchema,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Send a friend request to another user.
    
    Args:
        user_id: ID of user sending the request
        request_data: Contains to_user_id
    
    Returns:
        Friend request details
    """
    friend_request = await friendship_repo.send_friend_request(user_id, request_data.to_user_id)
    return FriendRequestSchema.from_db_model(friend_request).model_dump(by_alias=True)


@app.get("/users/{user_id}/friend-requests/", include_in_schema=False)
async def get_friend_requests(
    user_id: int,
    q: str,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Get friend requests for a user.
    
    Args:
        user_id: User ID
        q: Query parameter - either "incoming" or "outgoing"
    
    Returns:
        List of friend requests
    """
    if q == "incoming":
        requests = await friendship_repo.get_incoming_requests(user_id)
    elif q == "outgoing":
        requests = await friendship_repo.get_outgoing_requests(user_id)
    else:
        raise HTTPException(status_code=400, detail="Query parameter 'q' must be 'incoming' or 'outgoing'")
    
    return [FriendRequestSchema.from_db_model(req).model_dump(by_alias=True) for req in requests]


@app.put("/users/{user_id}/friend-requests/{other_id}", status_code=204, include_in_schema=False)
async def accept_friend_request(
    user_id: int,
    other_id: int,
    response: Response,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Accept a friend request.
    
    Args:
        user_id: User accepting the request (recipient)
        other_id: User who sent the request
    """
    await friendship_repo.accept_friend_request(user_id, other_id)
    return Response(status_code=204)


@app.delete("/users/{user_id}/friend-requests/{other_id}", status_code=204, include_in_schema=False)
async def delete_friend_request(
    user_id: int,
    other_id: int,
    response: Response,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Delete (reject or cancel) a friend request.
    - If you received the request: reject it
    - If you sent the request: cancel it
    
    Args:
        user_id: Current user
        other_id: Other user in the request
    """
    # Try to cancel (user_id is sender)
    try:
        await friendship_repo.cancel_friend_request(user_id, other_id)
        return Response(status_code=204)
    except HTTPException:
        pass
    
    # Try to reject (user_id is recipient)
    await friendship_repo.reject_friend_request(user_id, other_id)
    return Response(status_code=204)


# ==================== FRIENDS ROUTES ====================

@app.get("/users/{user_id}/friends/", include_in_schema=False)
async def list_friends(
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    List all friends of a user.
    
    Returns:
        List of user objects (without passwords)
    """
    friends = await friendship_repo.get_friends(user_id)
    return [UserSchema.from_db_model(friend).model_dump() for friend in friends]


@app.get("/users/{user_id}/friends/{friend_identifier}", include_in_schema=False)
async def get_friend(
    user_id: int,
    friend_identifier: str,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Get a specific friend by name or ID.
    
    Args:
        user_id: Current user ID
        friend_identifier: Friend's name or ID
    
    Returns:
        User object (without password)
    """
    # Try as ID first
    if friend_identifier.isdigit():
        friend = await friendship_repo.get_friend_by_id(user_id, int(friend_identifier))
        if friend:
            return UserSchema.from_db_model(friend).model_dump()
    
    # Try as name
    friend = await friendship_repo.get_friend_by_name(user_id, friend_identifier)
    if friend:
        return UserSchema.from_db_model(friend).model_dump()
    
    raise HTTPException(status_code=404, detail="Friend not found")

@app.delete("/users/{user_id}/friends/{friend_id}", status_code=204, include_in_schema=False)
async def unfriend(
    user_id: int,
    friend_id: int,
    response: Response,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository)
):
    """
    Remove a friendship.
    
    Args:
        user_id: Current user
        friend_id: Friend to remove
    """
    await friendship_repo.unfriend(user_id, friend_id)

# issue14: profile picture avatar
@app.get("/users/{user_id}/avatar", include_in_schema=False)
async def get_avatar(user_id: int, user_repo: UserRepository = Depends(get_user_repository)):
    """
    Get a user's profile picture.
    
    Args:
        user_id: User ID
    
    Returns:
        Image file
    
    Raises:
        404: If user doesn't exist or has no avatar
    """
    # Check user exists
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check avatar exists
    avatar_path = get_avatar_path(user_id)
    if not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Avatar not found")
    
    # Return image file
    return FileResponse(
        path=avatar_path,
        media_type="image/webp",
        filename=f"user_{user_id}_avatar.webp"
    )


@app.post("/users/{user_id}/avatar", status_code=201, include_in_schema=False)
async def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Upload a profile picture for a user.
    
    Args:
        user_id: User ID
        file: Image file (multipart/form-data)
    
    Returns:
        Success message
    
    Raises:
        404: If user doesn't exist
        409: If avatar already exists (use PUT to update)
        400: If file format is invalid
    """
    # Check user exists
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if avatar already exists
    if avatar_exists(user_id):
        raise HTTPException(status_code=409, detail="Avatar already exists. Use PUT to update.")
    
    # Save avatar
    avatar_path = await save_avatar(user_id, file)
    
    # Update user record
    stmt = update(User).where(User.id == user_id).values(avatar_path=avatar_path)
    user_repo.session.execute(stmt)
    user_repo.session.commit()
    
    return {"message": "Avatar uploaded successfully", "avatar_url": f"/users/{user_id}/avatar"}


@app.put("/users/{user_id}/avatar", status_code=200, include_in_schema=False)
async def update_avatar(
    user_id: int,
    file: UploadFile = File(...),
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Update a user's profile picture.
    
    Args:
        user_id: User ID
        file: New image file (multipart/form-data)
    
    Returns:
        Success message
    
    Raises:
        404: If user doesn't exist
        400: If file format is invalid
    """
    # Check user exists
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Delete old avatar if exists
    delete_avatar(user_id)
    
    # Save new avatar
    avatar_path = await save_avatar(user_id, file)
    
    # Update user record
    from sqlalchemy import update
    stmt = update(User).where(User.id == user_id).values(avatar_path=avatar_path)
    user_repo.session.execute(stmt)
    user_repo.session.commit()
    
    return {"message": "Avatar updated successfully", "avatar_url": f"/users/{user_id}/avatar"}


@app.delete("/users/{user_id}/avatar", status_code=204, include_in_schema=False)
async def delete_user_avatar(
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Delete a user's profile picture.
    
    Args:
        user_id: User ID
    
    Raises:
        404: If user doesn't exist or has no avatar
    """
    # Check user exists
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check avatar exists
    if not avatar_exists(user_id):
        raise HTTPException(status_code=404, detail="Avatar not found")
    
    # Delete avatar file
    delete_avatar(user_id)
    
    # Update user record
    from sqlalchemy import update
    stmt = update(User).where(User.id == user_id).values(avatar_path=None)
    user_repo.session.execute(stmt)
    user_repo.session.commit()
    
    return Response(status_code=204)


# ==================== JWT AUTHENTICATION ====================

@app.post("/v2/authentications/", status_code=200, response_model=AuthenticationResponseSchema)
async def create_authentication(
    auth_data: AuthenticationCreateSchema,
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Create JWT token for authentication.
    
    - Verifies username and password
    - Enforces max 1 hour token duration
    - Revokes all previous tokens for this user
    """
    # Verify user exists
    user = await user_repo.get_by_name(auth_data.name)
    if not user:
        user = await user_repo.get_by_email(auth_data.name)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not verify_password(auth_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Parse expiry datetime
    try:
        requested_expiry = datetime.strptime(auth_data.expiry, "%Y-%m-%d %H:%M:%S")
        # Make it timezone-aware
        requested_expiry = requested_expiry.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use 'YYYY-MM-DD HH:MM:SS'")
    
    # Enforce 1-hour maximum
    now = datetime.now(timezone.utc)
    max_expiry = now + timedelta(hours=1)
    
    # Check if expiry is in the past
    if requested_expiry <= now:
        raise HTTPException(status_code=400, detail="Expiry must be in the future")
    
    # Use the earlier of requested_expiry or max_expiry
    actual_expiry = min(requested_expiry, max_expiry)
    
    # Create JWT token
    token = create_jwt(user.id, user.tier, actual_expiry)
    
    return {"jwt": token}


@app.delete("/v2/authentications/", status_code=204)
async def delete_authentication(auth_data: AuthenticationDeleteSchema):
    """
    Revoke a JWT token immediately.
    
    The token will be invalid for all future requests.
    """
    revoke_jwt(auth_data.jwt)
    return Response(status_code=204)


def verify_user_auth(user_id: int, password: Optional[str], jwt_token: Optional[str], hashed_password: str) -> None:
    """
    Verify user authentication using either password or JWT.
    
    Raises:
        HTTPException: If neither auth method provided or both fail
    """
    # Normalize blanks
    pwd = (password or "").strip() or None
    tok = (jwt_token or "").strip() or None

    if tok:
        authenticated_user_id = verify_jwt(tok)
        if authenticated_user_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        return
    
    if pwd:
        if not verify_password(pwd, hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect password")
        return
    
    raise HTTPException(status_code=401, detail="Either jwt or password required")


# v2 API endpoints:

# List users /v2/users
    # none of the read operations reveal the users password hash
@app.get("/v2/users/")
async def list_users_v2(user_repo: UserRepository = Depends(get_user_repository)):
    """
    Retrieve all users from the database.
    """
    try:
        # Handle async vs sync repo
        maybe = user_repo.get_all()
        user_models = await maybe if inspect.isawaitable(maybe) else maybe
        
        users = []
        for model in user_models:
            # Use getattr to be safe, but fallback to defaults if DB is messy
            users.append({
                "id": getattr(model, "id", None),
                "name": getattr(model, "name", "Unknown"),
                "email": getattr(model, "email", "Unknown"),
                "timezone": getattr(model, "timezone", "UTC")
            })
        return {'users': users}
    except Exception as exc:
        logger.error(f"Failed to list users: {exc}", exc_info=True)  # Log to console/file instead
        raise HTTPException(status_code=500, detail="Internal Server Error")
# Get user by name /v2/users/{user_name}
# Get user by id /v2/users/{user_id}
    # none of the read operations reveal the users password hash
@app.get("/v2/users/{identifier}")
async def get_user_v2(identifier: str, user_repo: UserRepository = Depends(get_user_repository)):
    """
    Retrieve a specific user by username or user ID.
    
    Args:
        identifier: Username or user ID to search for
        user_repo: UserRepository dependency injection
    
    Returns:
        dict: User information if found (excludes password)

    Raises:
        404 Not Found: If user doesn't exist
    """
    # Try to interpret identifier as an int ID
    if identifier.isdigit():
        user = await user_repo.get_by_id(int(identifier))
    else:
        user = await user_repo.get_by_name(identifier)
    
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "tier": user.tier,
            "timezone": user.timezone
        }
    }

# Create user /v2/users/
@app.post("/v2/users/", status_code=201)
async def create_user_v2(user: UserCreateSchema, response: Response, user_repo: UserRepository = Depends(get_user_repository)):
    """
    Create a new user with email and password.
    
    Args:
        user: UserCreateSchema containing name, email, and password
        response: FastAPI Response object for setting status codes
        user_repo: UserRepository dependency injection
        
    Returns:
        User name, user email, and user ID
        
    Raises:
        409 Conflict: If username or email already exists
    """

    # SECURITY CHECK: Enforce Minimum Password Length
    if len(user.password) < 8:
        raise HTTPException(
            status_code=400, 
            detail="Password must be at least 8 characters long."
        )

    try:
        # Create user with hashed password
        new_user = await user_repo.create(user.name, user.email, user.password, user.timezone)
        return {"user": {
                "name": new_user.name,
                "email": new_user.email,
                "id": new_user.id,
                "tier": new_user.tier,
                "timezone": new_user.timezone
        }}
    except IntegrityError:
        _sess = getattr(user_repo, "session", None) or getattr(user_repo, "db", None)
        if _sess is not None:
            _sess.rollback()
        raise HTTPException(status_code=409, detail="User with this name or email already exists")


# Update user (authenticated) /v2/users/{ser_id}
    # Whichever fields are in the JSON body request will be updated, except for the password and id fields
    # Password can be changed with a new_password field
@app.put("/v2/users/{user_id}", status_code=200)
async def update_user_v2(
    user_id: int,
    update_data: UserUpdateSchema,
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme), 
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Update user information by user ID.
    
    Args:
        user_id: ID of the user to update
        update_data: UserUpdateSchema containing fields to update
        user_repo: UserRepository dependency injection

    Returns:
        dict: Updated user information (excludes password)

    Raises:
        404 Not Found: If user doesn't exist
        401 Unauthorized: If current password is incorrect
        409 Conflict: If new name or email already exists
    """
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

   # Accept either JWT or password; enforce identity match if JWT
    jwt_token = creds.credentials if creds else None

    verify_user_auth(
        user_id=user_id,
        password=update_data.password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    # Prepare update fields
    update_fields = {}
    if update_data.name is not None:
        update_fields['name'] = update_data.name
    if update_data.email is not None:
        update_fields['email'] = update_data.email
    if update_data.new_password is not None:
        update_fields['password'] = update_data.new_password

    try:
        updated_user = user_repo.update(user_id, **update_fields)
        if inspect.isawaitable(updated_user): 
            updated_user = await updated_user
        return {
            "user": {
                "id": updated_user.id,
                "name": updated_user.name,
                "email": updated_user.email,
                "tier": updated_user.tier,
                "timezone": updated_user.timezone
            }
        }
    except IntegrityError:
        _sess = getattr(user_repo, "session", None) or getattr(user_repo, "db", None)
        if _sess is not None:
            _sess.rollback()
        raise HTTPException(status_code=409, detail="User with this name or email already exists")



# Delete user (authenticated) /v2/users/{user_id}
@app.delete("/v2/users/{user_id}", status_code=204)
async def delete_user_authenticated_v2(
    user_id: int, 
    body: Optional[UserDeleteSchema] = None,  
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme), 
    user_repo: UserRepository = Depends(get_user_repository)
):
    """
    Delete a user by ID. 
    Requires either a valid Password (in body) OR a valid JWT (in header).
    """
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    jwt_token = creds.credentials if creds else None
    password_input = body.password if body else None

    verify_user_auth(
        user_id=user_id,
        password=password_input,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    await user_repo.delete(user.name)
    return Response(status_code=204)

# Issue 30 Avatars: /v2/users/{user_id}/avatar

@app.get("/v2/users/{user_id}/avatar")
async def get_avatar_v2(user_id: int, user_repo: UserRepository = Depends(get_user_repository)):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    avatar_path = get_avatar_path(user_id)
    if not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(path=avatar_path, media_type="image/webp", filename=f"user_{user_id}_avatar.webp")

@app.post("/v2/users/{user_id}/avatar", status_code=201)
async def upload_avatar_v2(
    user_id: int,
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),                      # now optional (JWT can be used)
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Accept either JWT or password
    jwt_token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    if avatar_exists(user_id):
        raise HTTPException(status_code=409, detail="Avatar already exists. Use PUT to update.")

    avatar_path = await save_avatar(user_id, file)
    try:
        user_repo.session.execute(update(User).where(User.id == user_id).values(avatar_path=avatar_path))
        user_repo.session.commit()
    except Exception:
        user_repo.session.rollback()
        delete_avatar(user_id)  # keep FS and DB consistent on failure
        raise
    return {"message": "Avatar uploaded successfully", "avatar_url": f"/v2/users/{user_id}/avatar"}

@app.put("/v2/users/{user_id}/avatar")
async def update_avatar_v2(
    user_id: int,
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Accept either JWT or password
    jwt_token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    delete_avatar(user_id)  # ok if it didn’t exist
    avatar_path = await save_avatar(user_id, file)
    try:
        user_repo.session.execute(update(User).where(User.id == user_id).values(avatar_path=avatar_path))
        user_repo.session.commit()
    except Exception:
        user_repo.session.rollback()
        delete_avatar(user_id)
        raise
    return {"message": "Avatar updated successfully", "avatar_url": f"/v2/users/{user_id}/avatar"}

@app.delete("/v2/users/{user_id}/avatar", status_code=204)
async def delete_user_avatar_v2(
    user_id: int,
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Accept either JWT or password
    jwt_token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )
    if not avatar_exists(user_id):
        raise HTTPException(status_code=404, detail="Avatar not found")

    delete_avatar(user_id)
    user_repo.session.execute(update(User).where(User.id == user_id).values(avatar_path=None))
    user_repo.session.commit()
    return Response(status_code=204)


# Issue 30 v2 user friend requests
@app.get("/v2/users/{user_id}/friend-requests/")
async def v2_get_friend_requests(
    user_id: int,
    q: Literal["incoming", "outgoing"],  # ?q=incoming | ?q=outgoing
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    """
    Get unanswered friend requests for a user.
    - q=incoming → requests sent TO this user
    - q=outgoing → requests sent BY this user
    """
    if q == "incoming":
        requests = await friendship_repo.get_incoming_requests(user_id)
    else:  # q == "outgoing"
        requests = await friendship_repo.get_outgoing_requests(user_id)

    return [
        FriendRequestSchema.from_db_model(r).model_dump(by_alias=True)
        for r in requests
    ]


@app.post("/v2/users/{user_id}/friend-requests/", status_code=201)
async def v2_send_friend_request(
    user_id: int,
    to_user_id: int = Form(...),
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Create a friend request FROM {user_id} TO body.to_user_id.
    Returns the request payload:
    { "from": <id>, "to": <id>, "sent_timestamp": <iso> }
    """
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    req = await friendship_repo.send_friend_request(user_id, to_user_id)
    return FriendRequestSchema.from_db_model(req).model_dump(by_alias=True)


@app.put("/v2/users/{user_id}/friend-requests/{other_id}", status_code=204)
async def v2_accept_friend_request(
    user_id: int,
    other_id: int,
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Accept a friend request (the requestee answers).
    - user_id: the recipient (requestee)
    - other_id: the sender (requester)
    """
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    await friendship_repo.accept_friend_request(user_id, other_id)
    return Response(status_code=204)


@app.delete("/v2/users/{user_id}/friend-requests/{other_id}", status_code=204)
async def v2_delete_friend_request(
    user_id: int,
    other_id: int,
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Delete a friend request:
    - If user_id sent it → cancel
    - If user_id received it → reject
    """
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    # Try to cancel (user_id is the sender)
    try:
        await friendship_repo.cancel_friend_request(user_id, other_id)
        return Response(status_code=204)
    except HTTPException:
        # Not the sender; fall through and try reject
        pass

    # Try to reject (user_id is the recipient)
    await friendship_repo.reject_friend_request(user_id, other_id)
    return Response(status_code=204)

# Issue 30 v2 User Friends
@app.get("/v2/users/{user_id}/friends/")
async def v2_list_friends(
    user_id: int,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    """
    List all friends of a user (public user objects only).
    """
    friends = await friendship_repo.get_friends(user_id)
    return [UserSchema.from_db_model(f).model_dump() for f in friends]


@app.get("/v2/users/{user_id}/friends/{friend_id:int}")
async def v2_get_friend_by_id(
    user_id: int,
    friend_id: int,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    friend = await friendship_repo.get_friend_by_id(user_id, friend_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found")
    return UserSchema.from_db_model(friend).model_dump()


@app.get("/v2/users/{user_id}/friends/{friend_name}")
async def v2_get_friend_by_name(
    user_id: int,
    friend_name: str,
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    friend = await friendship_repo.get_friend_by_name(user_id, friend_name)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found")
    return UserSchema.from_db_model(friend).model_dump()


@app.delete("/v2/users/{user_id}/friends/{friend_id:int}", status_code=204)
async def v2_unfriend_by_id(
    user_id: int,
    friend_id: int,
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    await friendship_repo.unfriend(user_id, friend_id)
    return Response(status_code=204)


@app.delete("/v2/users/{user_id}/friends/{friend_name}", status_code=204)
async def v2_unfriend_by_name(
    user_id: int,
    friend_name: str,
    password: Optional[str] = Form(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    friend = await friendship_repo.get_friend_by_name(user_id, friend_name)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found")
    await friendship_repo.unfriend(user_id, friend.id)
    return Response(status_code=204)

# Mount the NiceGUI admin interface

ui.run_with(app,
            mount_path="/admin",
            favicon="👤",
            title="User Admin",
            storage_secret=os.getenv("STORAGE_SECRET", "dev_secret_change_in_production"))

# ==================== SCHEDULE ROUTES ====================

@app.post("/v2/users/{user_id}/schedule/", status_code=201)
async def create_schedule_entry(
    user_id: int,
    entry: ScheduleEntryCreate,
    password: Optional[str] = Query(None, description="Password for authentication (alternative to JWT)"),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    schedule_repo: ScheduleRepository = Depends(get_schedule_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """Create a schedule entry (busy or free time slot)."""
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    # FastAPI/Pydantic automatically parses ISO format datetime strings to datetime objects
    # Ensure timezone-aware (Pydantic handles this, but we ensure UTC if None)
    if entry.start_time.tzinfo is None:
        entry.start_time = entry.start_time.replace(tzinfo=timezone.utc)
    if entry.end_time.tzinfo is None:
        entry.end_time = entry.end_time.replace(tzinfo=timezone.utc)

    schedule_entry = await schedule_repo.create_schedule_entry(
        user_id=user_id,
        start_time=entry.start_time,
        end_time=entry.end_time,
        is_busy=entry.is_busy,
        title=entry.title
    )

    # FastAPI automatically serializes datetime to ISO format in JSON response
    return ScheduleEntryOut.model_validate(schedule_entry).model_dump()


@app.get("/v2/users/{user_id}/schedule/")
async def get_user_schedule(
    user_id: int,
    start_date: Optional[datetime] = Query(None, description="Filter schedule entries from this datetime (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="Filter schedule entries until this datetime (ISO format)"),
    password: Optional[str] = Query(None, description="Password for authentication (alternative to JWT)"),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    schedule_repo: ScheduleRepository = Depends(get_schedule_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    """Get a user's schedule entries. Users can view their own schedule or friends can view each other's schedules."""
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # FastAPI automatically parses ISO format datetime strings from query parameters
    # Ensure timezone-aware
    start_dt = start_date
    end_dt = end_date
    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    # Verify authentication
    jwt_token = creds.credentials if creds else None
    authenticated_user_id = None

    if jwt_token:
        try:
            authenticated_user_id = verify_jwt(jwt_token)
        except HTTPException:
            pass

    if not authenticated_user_id and password:
        # Verify password for the user being viewed
        if not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect password")
        authenticated_user_id = user_id

    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Authentication required to view schedules")

    # If viewing own schedule, allow
    if authenticated_user_id == user_id:
        entries = await schedule_repo.get_user_schedule(user_id, start_dt, end_dt)
        # FastAPI automatically serializes datetime to ISO format in JSON response
        return [ScheduleEntryOut.model_validate(e).model_dump() for e in entries]

    # If viewing friend's schedule, verify friendship
    friend = await friendship_repo.get_friend_by_id(authenticated_user_id, user_id)
    if not friend:
        raise HTTPException(status_code=403, detail="You can only view schedules of your friends")

    entries = await schedule_repo.get_user_schedule(user_id, start_dt, end_dt)
    # FastAPI automatically serializes datetime to ISO format in JSON response
    return [ScheduleEntryOut.model_validate(e).model_dump() for e in entries]


@app.get("/v2/users/{user_id}/friends/{friend_id}/schedule/")
async def get_friend_schedule(
    user_id: int,
    friend_id: int,
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    password: Optional[str] = Query(None),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    user_repo: UserRepository = Depends(get_user_repository),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    """
    Get a friend's GENERATED schedule (Tasks + Times).
    """
    # 1. Auth Check
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    friend = await user_repo.get_by_id(friend_id)
    if not friend:
        raise HTTPException(status_code=404, detail="Friend not found")

    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    # 2. Friendship Check
    friend_check = await friendship_repo.get_friend_by_id(user_id, friend_id)
    if not friend_check:
        raise HTTPException(status_code=403, detail="You can only view schedules of your friends")

    # 3. Query GeneratedSchedule (Joined with Task for names)
    stmt = select(GeneratedSchedule, Task.name).join(
        Task, Task.id == GeneratedSchedule.task_id
    ).where(
        GeneratedSchedule.user_id == friend_id
    )

    # Date Filtering
    if start_date:
        # Ensure UTC
        if start_date.tzinfo is None: 
            start_date = start_date.replace(tzinfo=timezone.utc)
        stmt = stmt.where(GeneratedSchedule.scheduled_end >= start_date)
    
    if end_date:
        if end_date.tzinfo is None: 
            end_date = end_date.replace(tzinfo=timezone.utc)
        stmt = stmt.where(GeneratedSchedule.scheduled_start <= end_date)

    stmt = stmt.order_by(GeneratedSchedule.scheduled_start)
    
    # Execute
    # We use user_repo.session because it's available, 
    # effectively utilizing the same DB connection logic.
    results = user_repo.session.execute(stmt).all()

    # 4. Format Output
    # We map 'scheduled_start' -> 'start_time' to match the frontend expectations
    output = []
    for sched, task_name in results:
        output.append({
            "id": str(sched.id),
            "start_time": sched.scheduled_start,
            "end_time": sched.scheduled_end,
            "is_busy": True, # Scheduled tasks are busy
            "title": task_name,
            "reasoning": sched.reasoning
        })

    return output


@app.post("/v2/schedule/find-common-time")
async def find_common_free_time(
    request: FindCommonTimeRequest,
    password: Optional[str] = Query(None, description="Password for authentication (alternative to JWT)"),
    creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    schedule_repo: ScheduleRepository = Depends(get_schedule_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    friendship_repo: FriendshipRepository = Depends(get_friendship_repository),
):
    """
    Find overlapping free time for multiple users using Positive Availability logic.
    
    Only considers explicit free time slots (is_busy=False). Does NOT assume 24/7 availability.
    If any user has no free time slots in the date range, returns empty results.
    All users must be friends with the authenticated user.
    """
    if len(request.user_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 user IDs required")

    # Verify authentication - use first user_id as the authenticated user
    authenticated_user_id = request.user_ids[0]
    user = await user_repo.get_by_id(authenticated_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    jwt_token = creds.credentials if creds else None
    verify_user_auth(
        user_id=authenticated_user_id,
        password=password,
        jwt_token=jwt_token,
        hashed_password=user.hashed_password,
    )

    # Verify all users in the list are friends with the authenticated user
    for user_id in request.user_ids[1:]:
        friend = await friendship_repo.get_friend_by_id(authenticated_user_id, user_id)
        if not friend:
            raise HTTPException(status_code=403, detail=f"User {user_id} is not your friend")

    # FastAPI/Pydantic automatically parses ISO format datetime strings to datetime objects
    # Ensure timezone-aware
    if request.start_date.tzinfo is None:
        request.start_date = request.start_date.replace(tzinfo=timezone.utc)
    if request.end_date.tzinfo is None:
        request.end_date = request.end_date.replace(tzinfo=timezone.utc)

    if request.start_date >= request.end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")

    common_times = schedule_repo.find_common_free_time(
        user_ids=request.user_ids,
        start_date=request.start_date,
        end_date=request.end_date,
        min_duration_minutes=request.min_duration_minutes
    )

    return {
        "common_free_times": common_times,
        "message": f"Found {len(common_times)} common free time slot(s)"
    }

frontend_path = os.path.join(os.path.dirname(__file__), "../frontend") 
if not os.path.exists(frontend_path):
    # Fallback if running from root
    frontend_path = "frontend"

app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")