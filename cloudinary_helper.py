# cloudinary_helper.py
import os
import cloudinary
import cloudinary.uploader

def init_cloudinary():
    url = os.getenv("CLOUDINARY_URL")
    if url:
        cloudinary.config(cloudinary_url=url, secure=True)
    else:
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True,
        )

def upload_media_local(local_path: str, folder: str = "video_reel"):
    """
    ローカルの生成物（動画/画像）を Cloudinary にアップロードして公開URLを返す。
    戻り値: (secure_url, resource_type)
    """
    init_cloudinary()
    res = cloudinary.uploader.upload(
        local_path,
        folder=folder,
        resource_type="auto",   # 画像/動画どちらも自動
        overwrite=True,
    )
    return res.get("secure_url"), res.get("resource_type", "image")
