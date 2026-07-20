import boto3
import mimetypes
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


def upload_audio(local_path: str, key: str, content_type: str | None = None) -> str:
    """上传本地音频文件到 R2，返回公开访问 URL"""
    r2 = providers.R2
    if not content_type:
        content_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    _client().upload_file(
        local_path,
        r2.BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{r2.PUBLIC_URL.rstrip('/')}/{key}"


def delete_audio(key: str) -> None:
    """删除 R2 中的收藏音频。"""
    if not key:
        return
    _client().delete_object(Bucket=providers.R2.BUCKET_NAME, Key=key)


def get_audio(key: str, byte_range: str | None = None):
    """读取 R2 音频对象；byte_range 用于移动端媒体播放器的分段请求。"""
    if not key:
        raise ValueError("Audio key is empty")
    kwargs = {"Bucket": providers.R2.BUCKET_NAME, "Key": key}
    if byte_range:
        kwargs["Range"] = byte_range
    return _client().get_object(**kwargs)
