"""Загрузка файлов в S3-совместимое хранилище (AWS Signature V4, без boto3)."""

import datetime
import hashlib
import hmac
import mimetypes
import os
import urllib.parse
import uuid

import requests


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sigv4_headers(
    method: str,
    host: str,
    path: str,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    payload: bytes,
    extra_headers: dict | None = None,
    now: datetime.datetime | None = None,
    sign_content_sha: bool = True,
) -> dict:
    """Возвращает заголовки с подписью AWS SigV4 для запроса без query string."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = _sha256(payload)

    headers = {"host": host, "x-amz-date": amz_date}
    if sign_content_sha:  # обязателен для S3
        headers["x-amz-content-sha256"] = payload_hash
    headers.update({k.lower(): v for k, v in (extra_headers or {}).items()})

    signed_names = sorted(headers)
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_path = urllib.parse.quote(path, safe="/")
    canonical_request = "\n".join(
        [method, canonical_path, "", canonical_headers, signed_headers, payload_hash]
    )

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical_request.encode())]
    )

    key = _hmac(f"AWS4{secret_key}".encode(), date_stamp)
    key = _hmac(key, region)
    key = _hmac(key, service)
    key = _hmac(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    del headers["host"]  # requests выставит его сам
    return headers


class S3Storage:
    def __init__(self):
        self.endpoint = os.environ.get("S3_ENDPOINT", "")
        self.region = os.environ.get("S3_REGION", "")
        self.bucket = os.environ.get("S3_BUCKET", "")
        self.access_key = os.environ.get("S3_ACCESS_KEY", "")
        self.secret_key = os.environ.get("S3_SECRET_KEY", "")
        # Домен публичной раздачи (у Selectel — *.selstorage.ru из панели);
        # загрузка идёт через S3-endpoint, а в посты вставляется этот домен
        self.public_base = os.environ.get("S3_PUBLIC_BASE", "").rstrip("/")

    @property
    def configured(self) -> bool:
        return all(
            (self.endpoint, self.region, self.bucket, self.access_key, self.secret_key)
        )

    def upload(self, filename: str, blob: bytes) -> tuple[bool, str]:
        """Кладёт файл в бакет с публичным доступом, возвращает (ok, url|ошибка)."""
        ext = os.path.splitext(filename)[1].lower() or ".jpg"
        key = f"uploads/{uuid.uuid4().hex}{ext}"
        path = f"/{self.bucket}/{key}"
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        headers = sigv4_headers(
            "PUT",
            self.endpoint,
            path,
            self.region,
            "s3",
            self.access_key,
            self.secret_key,
            blob,
            extra_headers={"x-amz-acl": "public-read", "content-type": content_type},
        )
        headers["content-type"] = content_type
        try:
            resp = requests.put(
                f"https://{self.endpoint}{path}", data=blob, headers=headers, timeout=120
            )
        except requests.RequestException as e:
            return False, f"S3 недоступен: {e}"
        if resp.status_code != 200:
            return False, f"S3 ответил {resp.status_code}: {resp.text[:300]}"
        if self.public_base:
            return True, f"{self.public_base}/{key}"
        return True, f"https://{self.endpoint}{path}"
