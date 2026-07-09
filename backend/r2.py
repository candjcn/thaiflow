import os
import boto3
from botocore.config import Config


def _client():
    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    if not all([account_id, access_key, secret_key]):
        raise ValueError("R2 credentials not configured (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_audio(local_path: str, key: str) -> str:
    """上传本地音频文件到 R2，返回公开访问 URL"""
    bucket = os.getenv("R2_BUCKET_NAME", "reelspeak-audio")
    public_base = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    _client().upload_file(
        local_path,
        bucket,
        key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )
    return f"{public_base}/{key}"
