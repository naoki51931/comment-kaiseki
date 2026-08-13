from pathlib import Path
import socket
import struct
from uuid import uuid4

from app.config import settings


ALLOWED_SUFFIXES = {".kif", ".ki2", ".csa", ".txt"}


class MalwareDetectedError(ValueError):
    pass


def scan_content(content: bytes) -> None:
    if not settings.malware_scan_enabled:
        return
    with socket.create_connection((settings.clamd_host, settings.clamd_port), timeout=10) as connection:
        connection.sendall(b"zINSTREAM\0")
        for offset in range(0, len(content), 8192):
            chunk = content[offset : offset + 8192]
            connection.sendall(struct.pack(">I", len(chunk)) + chunk)
        connection.sendall(struct.pack(">I", 0))
        response = connection.recv(4096).decode(errors="replace")
    if "FOUND" in response:
        raise MalwareDetectedError("アップロードファイルからマルウェアが検出されました。")
    if "OK" not in response:
        raise RuntimeError("マルウェア検査を完了できませんでした。")


def save_private_file(content: bytes, suffix: str) -> Path | str:
    scan_content(content)
    safe_suffix = suffix.lower() if suffix.lower() in ALLOWED_SUFFIXES else ".bin"
    object_name = f"{uuid4().hex}{safe_suffix}"
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKETが設定されていません。")
        import boto3

        key = f"{settings.s3_prefix.strip('/')}/{object_name}"
        boto3.client("s3").put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=content,
            ACL="private",
            ServerSideEncryption="AES256",
            ContentType="application/octet-stream",
        )
        return f"s3://{settings.s3_bucket}/{key}"

    settings.upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = settings.upload_dir / object_name
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def save_private_kif(content: bytes) -> Path | str:
    return save_private_file(content, ".kif")


def remove_private_file(location: Path | str) -> None:
    text = str(location)
    if text.startswith("s3://"):
        import boto3

        bucket, key = text[5:].split("/", 1)
        boto3.client("s3").delete_object(Bucket=bucket, Key=key)
    else:
        Path(text).unlink(missing_ok=True)
