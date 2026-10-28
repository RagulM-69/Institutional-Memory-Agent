"""
Cryptographic utility module for encrypting and decrypting source credentials at rest.
Implements AES-256-GCM authenticated encryption with tenant-bound Additional Authenticated Data (AAD).
Conforms to database specification in db/migrations/001_init.sql:
Payload: [ Version (1B) || Nonce (12B) || Ciphertext + Auth Tag (16B) ]
AAD: org_id || ':' || (source_id or '')
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Optional, Union
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from apps.api.config import settings

_VERSION_BYTE = b"\x01"
_NONCE_LENGTH = 12
_TAG_LENGTH = 16
_MIN_PAYLOAD_LENGTH = 1 + _NONCE_LENGTH + _TAG_LENGTH


class CryptoError(Exception):
    """Base exception for cryptographic operations."""
    pass


class DecryptionError(CryptoError):
    """Raised when credential decryption or integrity verification fails."""
    pass


def _derive_master_key() -> bytes:
    """
    Derive a 256-bit AES key.
    Prefers settings.credential_encryption_key if set; otherwise derives
    deterministically via HKDF-SHA256 from the server's Supabase JWT secret.
    """
    custom_key = getattr(settings, "credential_encryption_key", None)
    if custom_key and custom_key.get_secret_value().strip():
        raw = custom_key.get_secret_value().strip()
        # If 64 hex characters, decode hex
        if len(raw) == 64:
            try:
                return bytes.fromhex(raw)
            except ValueError:
                pass
        # If 44-char base64, decode base64
        if len(raw) == 44:
            try:
                decoded = base64.b64decode(raw)
                if len(decoded) == 32:
                    return decoded
            except Exception:
                pass
        # Otherwise hash the custom key
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"institutional-memory-crypto-salt-v1",
            info=b"source-credential-encryption-key",
        )
        return hkdf.derive(raw.encode("utf-8"))

    # Fallback: derive from Supabase JWT secret or service role key
    fallback_seed = ""
    if settings.supabase_jwt_secret:
        fallback_seed = settings.supabase_jwt_secret.get_secret_value().strip()
    if not fallback_seed and settings.supabase_service_role_key:
        fallback_seed = settings.supabase_service_role_key.get_secret_value().strip()
    if not fallback_seed:
        fallback_seed = "institutional-memory-agent-default-fallback-key-2026"

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"institutional-memory-crypto-salt-v1",
        info=b"source-credential-encryption-key",
    )
    return hkdf.derive(fallback_seed.encode("utf-8"))


def _compute_aad(org_id: Union[UUID, str], source_id: Optional[Union[UUID, str]] = None) -> bytes:
    """Bind encryption cryptographically to tenant org_id and optional source_id."""
    s_id = str(source_id) if source_id else ""
    return f"{str(org_id)}:{s_id}".encode("utf-8")


def encrypt_credentials(
    payload: Union[Dict[str, Any], str],
    org_id: Union[UUID, str],
    source_id: Optional[Union[UUID, str]] = None,
) -> bytes:
    """
    Encrypt a credentials dictionary or string using AES-256-GCM.
    Returns binary payload conforming to 001_init.sql specification.
    """
    if isinstance(payload, dict):
        raw_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        raise CryptoError("Payload must be a dictionary or string")

    key = _derive_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LENGTH)
    aad = _compute_aad(org_id, source_id)

    ciphertext = aesgcm.encrypt(nonce, raw_bytes, aad)
    return _VERSION_BYTE + nonce + ciphertext


def decrypt_credentials(
    encrypted_bytes: bytes,
    org_id: Union[UUID, str],
    source_id: Optional[Union[UUID, str]] = None,
) -> Union[Dict[str, Any], str]:
    """
    Decrypt binary payload using AES-256-GCM with tenant-bound AAD verification.
    Returns parsed dictionary if JSON, or decoded string.
    Raises DecryptionError if verification or decryption fails.
    """
    if not encrypted_bytes or len(encrypted_bytes) < _MIN_PAYLOAD_LENGTH:
        raise DecryptionError("Encrypted payload is corrupted or too short")

    version = encrypted_bytes[:1]
    if version != _VERSION_BYTE:
        raise DecryptionError(f"Unsupported payload version: {version!r}")

    nonce = encrypted_bytes[1 : 1 + _NONCE_LENGTH]
    ciphertext = encrypted_bytes[1 + _NONCE_LENGTH :]

    key = _derive_master_key()
    aesgcm = AESGCM(key)
    aad = _compute_aad(org_id, source_id)

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
    except Exception as e:
        raise DecryptionError(f"Decryption integrity verification failed: {e}") from e

    text = decrypted_bytes.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text

