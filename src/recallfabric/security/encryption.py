import os

from cryptography.fernet import Fernet, InvalidToken


def get_fernet(encryption_key: str | None = None) -> Fernet | None:
    key = encryption_key or os.environ.get("RECALLFABRIC_ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        key_bytes = key.encode("utf-8") if isinstance(key, str) else key
        return Fernet(key_bytes)
    except Exception:
        return None


def encrypt_content(content: str, encryption_key: str | None = None) -> str:
    if not content:
        return content
    f = get_fernet(encryption_key)
    if f is None:
        return content
    try:
        ciphertext = f.encrypt(content.encode("utf-8"))
        return f"enc::{ciphertext.decode('utf-8')}"
    except Exception:
        return content


def decrypt_content(content: str, encryption_key: str | None = None) -> str:
    if not content:
        return content
    if not content.startswith("enc::"):
        return content
    f = get_fernet(encryption_key)
    if f is None:
        return content
    raw_cipher = content[5:]
    try:
        decrypted = f.decrypt(raw_cipher.encode("utf-8"))
        return decrypted.decode("utf-8")
    except (InvalidToken, Exception):
        return content
