import boto3
from botocore.config import Config
from config import providers


def _client():
    r2 = providers.R2
    if not all([r2.ACCOUNT_ID, r2.ACCESS_KEY_ID, r2.SECRET_ACCESS_KEY]):
        raise ValueError("R2 credentials not configured (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)")
    return boto3.client(
        "s3",
        endpoint_url=r2.ENDPOINT_URL,
        aws_access_key_id=r2.ACCESS_KEY_ID,
        aws_secret_access_key=r2.SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_audio(local_path: str, key: str) -> str:
    """上传本地音频文件到 R2，返回公开访问 URL"""
    r2 = providers.R2
    _client().upload_file(
        local_path,
        r2.BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )
    return f"{r2.PUBLIC_URL.rstrip('/')}/{key}"
