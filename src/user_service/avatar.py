"""
Avatar image processing and storage utilities.
"""
from PIL import Image
from pathlib import Path
from io import BytesIO
from fastapi import UploadFile, HTTPException
import os
import tempfile

# Detect if running in CI (GitHub Actions) or production
if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
    # Use temp directory in CI (writable)
    AVATAR_DIR = Path(tempfile.gettempdir()) / "avatars"
else:
    # Use /app/avatars in Docker production
    AVATAR_DIR = Path("/app/avatars")

AVATAR_DIR.mkdir(parents=True, exist_ok=True)

# Maximum size for avatars
AVATAR_SIZE = (256, 256)

# Allowed image formats
ALLOWED_FORMATS = {".webp", ".png", ".jpg", ".jpeg"}


def get_avatar_path(user_id: int) -> Path:
    """Get the file path for a user's avatar."""
    return AVATAR_DIR / f"user_{user_id}.webp"


async def save_avatar(user_id: int, file: UploadFile) -> str:
    """
    Process and save an avatar image.
    
    Args:
        user_id: User ID
        file: Uploaded image file
    
    Returns:
        str: Path where avatar was saved
    
    Raises:
        HTTPException: If file format is invalid
    """
    # Validate file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file format. Allowed: {', '.join(ALLOWED_FORMATS)}"
        )
    
    # Read image data
    contents = await file.read()
    
    try:
        # Open image with Pillow
        image = Image.open(BytesIO(contents))
        
        # Convert to RGB if needed (for transparency handling)
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
            image = background
        
        # Resize and crop to 256x256 (thumbnail with cropping)
        image.thumbnail(AVATAR_SIZE, Image.Resampling.LANCZOS)
        
        # Create a square image by cropping
        width, height = image.size
        if width != height:
            # Crop to square (center crop)
            min_dim = min(width, height)
            left = (width - min_dim) // 2
            top = (height - min_dim) // 2
            right = left + min_dim
            bottom = top + min_dim
            image = image.crop((left, top, right, bottom))
        
        # Resize to exact 256x256
        image = image.resize(AVATAR_SIZE, Image.Resampling.LANCZOS)
        
        # Save as WebP (efficient format)
        avatar_path = get_avatar_path(user_id)
        image.save(avatar_path, "WEBP", quality=85)
        
        return str(avatar_path)
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {str(e)}")


def delete_avatar(user_id: int) -> None:
    """Delete a user's avatar file if it exists."""
    avatar_path = get_avatar_path(user_id)
    if avatar_path.exists():
        avatar_path.unlink()


def avatar_exists(user_id: int) -> bool:
    """Check if avatar file exists for a user."""
    return get_avatar_path(user_id).exists()
