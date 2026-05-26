# utils/auth.py
"""
HMAC-SHA256 token 签发与验证。

Token 格式: {student_id}.{timestamp}.{signature}
  - student_id: 明文学号（接收方解开即可读）
  - timestamp: 签发时 Unix 时间戳（秒）
  - signature: HMAC-SHA256(secret, "{student_id}.{timestamp}")，URL-safe base64

安全保证:
  - 攻击者不知道 secret → 无法伪造新 token
  - 攻击者修改 student_id 或 timestamp → 签名对不上 → 拒
  - token 过期（now - timestamp > TOKEN_TTL_SECONDS）→ 拒
"""
import os
import hmac
import hashlib
import time
import base64
from typing import Optional

TOKEN_TTL_SECONDS = 24 * 60 * 60  # token 有效期 24 小时


def _get_secret() -> bytes:
    """从环境变量取 secret，缺失时直接抛错（fail-fast，不允许 silent fallback）"""
    secret = os.environ.get("AUTH_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "AUTH_SECRET_KEY 未配置。请在 .env 文件中添加该项，"
            "可用 `python -c \"import secrets; print(secrets.token_urlsafe(32))\"` 生成。"
        )
    return secret.encode("utf-8")


def _sign(payload: str) -> str:
    """对 payload 字符串做 HMAC-SHA256 签名，返回 URL-safe base64 字符串"""
    secret = _get_secret()
    mac = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest()
    # URL-safe base64，去掉填充 = 号（更紧凑，URL/header 友好）
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def generate_token(student_id: str) -> str:
    """
    为已认证用户签发 token。

    Args:
        student_id: 已通过密码验证的学号
    Returns:
        三段式 token: "{student_id}.{timestamp}.{signature}"
    """
    timestamp = str(int(time.time()))
    payload = f"{student_id}.{timestamp}"
    signature = _sign(payload)
    return f"{payload}.{signature}"


def verify_token(token: str) -> Optional[str]:
    """
    验证 token 有效性，成功返回其中的 student_id，失败返回 None。

    校验三件事:
      1. 格式正确（能拆成 3 段）
      2. 签名匹配（防伪造/防篡改）
      3. 未过期（now - timestamp < TOKEN_TTL_SECONDS）

    注意：用 hmac.compare_digest 而非 == 比对，避免时序攻击。
    """
    if not token or not isinstance(token, str):
        return None

    parts = token.split(".")
    if len(parts) != 3:
        return None

    student_id, timestamp_str, signature = parts

    # 1. 重算签名比对
    expected_signature = _sign(f"{student_id}.{timestamp_str}")
    # hmac.compare_digest 是常数时间比较，防止攻击者用时序差异逐字节爆破
    if not hmac.compare_digest(expected_signature, signature):
        return None

    # 2. 过期检查
    try:
        issued_at = int(timestamp_str)
    except ValueError:
        return None

    if time.time() - issued_at > TOKEN_TTL_SECONDS:
        return None

    return student_id