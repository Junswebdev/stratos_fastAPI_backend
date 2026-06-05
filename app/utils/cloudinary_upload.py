import os
import cloudinary
import cloudinary.uploader
from fastapi import HTTPException

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

def upload_to_cloudinary(
    file_bytes: bytes,
    folder: str,
    public_id: str = None,
    resource_type: str = "auto",
) -> str:
    """Upload bytes to Cloudinary and return the secure URL."""
    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            folder=folder,
            public_id=public_id,
            resource_type=resource_type,
            overwrite=True,
        )
        return result["secure_url"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")
