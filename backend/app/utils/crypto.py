"""
Cryptographic utilities for NeuroSQL.

Provides AES-256-GCM encryption and decryption for sensitive data
stored in the database — specifically database connection passwords.

Why AES-256-GCM?
    - AES-256: industry-standard symmetric encryption
    - GCM mode: authenticated encryption — detects tampering
    - Random nonce per encryption: same plaintext → different ciphertext
      (prevents pattern analysis of stored credentials)

Storage format:
    base64(nonce[12 bytes] + ciphertext + tag[16 bytes])

Key source:
    CREDENTIAL_ENCRYPTION_KEY environment variable
    Must be exactly 64 hex characters (= 32 bytes = 256 bits)

Usage:
    from app.utils.crypto import encrypt_credential, decrypt_credential

    # Encrypting before storage:
    encrypted = encrypt_credential("my_database_password")
    # Store 'encrypted' in database_connections.encrypted_password

    # Decrypting before use:
    password = decrypt_credential(encrypted)
    # Use 'password' to connect — never log or persist it
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Nonce size for AES-GCM: 12 bytes is the recommended size
# Using a different size requires additional length prefix — avoid
_NONCE_SIZE = 12


def _get_encryption_key() -> bytes:
    """
    Load and validate the AES-256 encryption key from settings.

    The key is stored as a 64-character hex string in the environment.
    We decode it to 32 bytes (256 bits) for use with AES-256.

    Returns:
        32-byte encryption key.

    Raises:
        ValueError: If the key is missing or not 64 hex characters.
    """
    settings = get_settings()
    hex_key = settings.credential_encryption_key

    if not hex_key:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"import secrets; "
            "print(secrets.token_hex(32))\""
        )

    try:
        key_bytes = bytes.fromhex(hex_key)
    except ValueError:
        raise ValueError(
            "CREDENTIAL_ENCRYPTION_KEY must be a valid hex string. "
            f"Got {len(hex_key)} characters, expected 64."
        )

    if len(key_bytes) != 32:
        raise ValueError(
            f"CREDENTIAL_ENCRYPTION_KEY must be 64 hex characters "
            f"(32 bytes). Got {len(key_bytes)} bytes."
        )

    return key_bytes


def encrypt_credential(plaintext: str) -> str:
    """
    Encrypt a credential string using AES-256-GCM.

    Generates a fresh random nonce for each encryption.
    The same plaintext encrypted twice will produce different output.

    Args:
        plaintext: The credential to encrypt (e.g. database password).

    Returns:
        Base64-encoded string: nonce + ciphertext + GCM tag.
        Safe to store in the database as TEXT.

    Raises:
        ValueError: If encryption key is invalid.
        Exception: If encryption fails.

    Example:
        encrypted = encrypt_credential("my_secret_password")
        # Store in database_connections.encrypted_password
    """
    if not plaintext:
        raise ValueError("Cannot encrypt empty credential")

    key = _get_encryption_key()
    aesgcm = AESGCM(key)

    # Generate a fresh random nonce for this encryption
    # CRITICAL: Never reuse a nonce with the same key
    nonce = os.urandom(_NONCE_SIZE)

    # Encrypt the plaintext
    # AESGCM.encrypt() returns ciphertext + 16-byte GCM authentication tag
    ciphertext_with_tag = aesgcm.encrypt(
        nonce,
        plaintext.encode("utf-8"),
        associated_data=None,  # No additional authenticated data
    )

    # Combine nonce + ciphertext+tag and base64-encode for storage
    # Format: nonce(12) | ciphertext+tag(variable)
    raw = nonce + ciphertext_with_tag
    encoded = base64.b64encode(raw).decode("utf-8")

    logger.debug("credential_encrypted", length=len(encoded))
    return encoded


def decrypt_credential(encrypted: str) -> str:
    """
    Decrypt a credential encrypted with encrypt_credential().

    Args:
        encrypted: Base64-encoded encrypted credential from the database.

    Returns:
        The original plaintext credential.

    Raises:
        ValueError: If the encrypted string is malformed or key is invalid.
        cryptography.exceptions.InvalidTag: If the ciphertext was tampered
            with. This is an important security signal — log and alert.

    Example:
        password = decrypt_credential(connection.encrypted_password)
        # Use password to connect — never log or re-persist it
    """
    if not encrypted:
        raise ValueError("Cannot decrypt empty credential")

    key = _get_encryption_key()
    aesgcm = AESGCM(key)

    try:
        # Decode from base64
        raw = base64.b64decode(encrypted.encode("utf-8"))
    except Exception:
        raise ValueError(
            "Encrypted credential is not valid base64. "
            "The stored value may be corrupted."
        )

    # Validate minimum length: nonce(12) + tag(16) = 28 bytes minimum
    if len(raw) < _NONCE_SIZE + 16:
        raise ValueError(
            f"Encrypted credential is too short ({len(raw)} bytes). "
            "Expected at least 28 bytes (nonce + GCM tag)."
        )

    # Split nonce from ciphertext+tag
    nonce = raw[:_NONCE_SIZE]
    ciphertext_with_tag = raw[_NONCE_SIZE:]

    try:
        # Decrypt and verify authentication tag
        # If the ciphertext was tampered with, this raises InvalidTag
        plaintext_bytes = aesgcm.decrypt(
            nonce,
            ciphertext_with_tag,
            associated_data=None,
        )
    except Exception as e:
        # Log the tamper attempt but don't expose details in the error
        logger.error(
            "credential_decryption_failed",
            error_type=type(e).__name__,
            hint="Possible key mismatch or data tampering",
        )
        raise ValueError(
            "Failed to decrypt credential. "
            "The encryption key may have changed or the data is corrupted."
        )

    plaintext = plaintext_bytes.decode("utf-8")
    logger.debug("credential_decrypted")
    return plaintext


def is_encrypted(value: str) -> bool:
    """
    Heuristic check: does this string look like an encrypted credential?

    Checks if the value is valid base64 and long enough to contain
    a nonce + some ciphertext. Used to avoid double-encrypting.

    Args:
        value: String to check.

    Returns:
        True if the value appears to be an AES-GCM encrypted credential.

    Note:
        This is a heuristic, not a guarantee. Use with caution.
    """
    try:
        raw = base64.b64decode(value.encode("utf-8"))
        return len(raw) >= _NONCE_SIZE + 16
    except Exception:
        return False