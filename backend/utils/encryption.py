"""
Encryption Utilities for Sensitive Data

Provides field-level encryption for sensitive data like TFN (Tax File Number).
Uses Fernet symmetric encryption (AES-128-CBC with HMAC) for secure storage.

Environment Variables:
    ENCRYPTION_KEY: Base64-encoded 32-byte key for Fernet encryption
                    Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage:
    from utils.encryption import encrypt_tfn, decrypt_tfn, mask_tfn
    
    # Encrypt for storage
    encrypted = encrypt_tfn("123456789")
    
    # Decrypt for use
    plaintext = decrypt_tfn(encrypted)
    
    # Mask for display
    masked = mask_tfn("123456789")  # Returns "***456789"

Security Notes:
    - Never log plaintext TFN values
    - Encryption key must be stored securely (env var, secrets manager)
    - Rotate keys periodically using re-encrypt functionality
    - TFN access should be audited
"""

import os
import base64
import logging
from typing import Optional, Tuple
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Environment variable name for encryption key
ENCRYPTION_KEY_ENV = "ENCRYPTION_KEY"

# Salt for key derivation (static for consistency)
KEY_DERIVATION_SALT = b"fdc_tax_core_v1_salt"


class EncryptionError(Exception):
    """Base exception for encryption errors"""
    pass


class KeyNotConfiguredError(EncryptionError):
    """Raised when encryption key is not configured"""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails"""
    pass


@lru_cache(maxsize=1)
def _get_fernet() -> Optional[Fernet]:
    """
    Get Fernet instance with configured key.
    Cached for performance.
    
    Returns:
        Fernet instance or None if not configured
    """
    key = os.environ.get(ENCRYPTION_KEY_ENV)
    
    if not key:
        logger.warning(f"{ENCRYPTION_KEY_ENV} not configured - encryption disabled")
        return None
    
    try:
        # Validate key format
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return fernet
    except Exception as e:
        logger.error(f"Invalid encryption key format: {e}")
        return None


def is_encryption_configured() -> bool:
    """Check if encryption is properly configured."""
    return _get_fernet() is not None


def encrypt_tfn(plaintext: str) -> Optional[str]:
    """
    Encrypt a Tax File Number for secure storage.
    
    Args:
        plaintext: The TFN to encrypt (9 digits)
        
    Returns:
        Base64-encoded encrypted string, or None if encryption disabled
        
    Raises:
        EncryptionError: If encryption fails
    """
    if not plaintext:
        return None
    
    # Validate TFN format (9 digits)
    cleaned = plaintext.replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != 9:
        logger.warning("Invalid TFN format - must be 9 digits")
        # Still encrypt whatever was provided for flexibility
    
    fernet = _get_fernet()
    
    if not fernet:
        logger.warning("Encryption not configured - storing TFN in plaintext is not recommended")
        return None
    
    try:
        encrypted = fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"TFN encryption failed: {e}")
        raise EncryptionError(f"Failed to encrypt TFN: {e}")


def decrypt_tfn(ciphertext: str) -> Optional[str]:
    """
    Decrypt a stored Tax File Number.
    
    Args:
        ciphertext: The encrypted TFN string
        
    Returns:
        Decrypted TFN string, or None if decryption fails
        
    Raises:
        DecryptionError: If decryption fails due to invalid data
        KeyNotConfiguredError: If encryption key not configured
    """
    if not ciphertext:
        return None
    
    fernet = _get_fernet()
    
    if not fernet:
        raise KeyNotConfiguredError("Encryption key not configured - cannot decrypt")
    
    try:
        decrypted = fernet.decrypt(ciphertext.encode('utf-8'))
        return decrypted.decode('utf-8')
    except InvalidToken:
        logger.error("TFN decryption failed - invalid token or wrong key")
        raise DecryptionError("Invalid encryption token - data may be corrupted or key mismatch")
    except Exception as e:
        logger.error(f"TFN decryption failed: {e}")
        raise DecryptionError(f"Failed to decrypt TFN: {e}")


def mask_tfn(tfn: str, visible_digits: int = 6) -> str:
    """
    Mask a TFN for display purposes.
    
    Args:
        tfn: The plaintext TFN
        visible_digits: Number of digits to show (default 6, shows last 6)
        
    Returns:
        Masked TFN string (e.g., "***456789")
    """
    if not tfn:
        return ""
    
    cleaned = tfn.replace(" ", "").replace("-", "")
    
    if len(cleaned) <= visible_digits:
        return cleaned
    
    hidden_count = len(cleaned) - visible_digits
    return "*" * hidden_count + cleaned[-visible_digits:]


def get_tfn_last_four(tfn: str) -> Optional[str]:
    """
    Extract last 4 digits of TFN for indexing/display.
    
    Args:
        tfn: The plaintext TFN
        
    Returns:
        Last 4 digits, or None if invalid
    """
    if not tfn:
        return None
    
    cleaned = tfn.replace(" ", "").replace("-", "")
    
    if len(cleaned) >= 4:
        return cleaned[-4:]
    
    return None


def encrypt_sensitive_field(plaintext: str, field_name: str = "field") -> Optional[str]:
    """
    Generic encryption for any sensitive field.
    
    Args:
        plaintext: Value to encrypt
        field_name: Name of field (for logging)
        
    Returns:
        Encrypted string or None
    """
    if not plaintext:
        return None
    
    fernet = _get_fernet()
    
    if not fernet:
        logger.warning(f"Encryption not configured for {field_name}")
        return None
    
    try:
        encrypted = fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption failed for {field_name}: {e}")
        raise EncryptionError(f"Failed to encrypt {field_name}: {e}")


def decrypt_sensitive_field(ciphertext: str, field_name: str = "field") -> Optional[str]:
    """
    Generic decryption for any sensitive field.
    
    Args:
        ciphertext: Encrypted value
        field_name: Name of field (for logging)
        
    Returns:
        Decrypted string or None
    """
    if not ciphertext:
        return None
    
    fernet = _get_fernet()
    
    if not fernet:
        raise KeyNotConfiguredError(f"Encryption key not configured - cannot decrypt {field_name}")
    
    try:
        decrypted = fernet.decrypt(ciphertext.encode('utf-8'))
        return decrypted.decode('utf-8')
    except InvalidToken:
        logger.error(f"Decryption failed for {field_name} - invalid token")
        raise DecryptionError(f"Invalid encryption token for {field_name}")
    except Exception as e:
        logger.error(f"Decryption failed for {field_name}: {e}")
        raise DecryptionError(f"Failed to decrypt {field_name}: {e}")


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.
    
    Returns:
        Base64-encoded key string
        
    Usage:
        key = generate_encryption_key()
        # Store in ENCRYPTION_KEY environment variable
    """
    return Fernet.generate_key().decode('utf-8')


def derive_key_from_password(password: str, salt: bytes = KEY_DERIVATION_SALT) -> str:
    """
    Derive an encryption key from a password.
    Useful for password-based encryption scenarios.
    
    Args:
        password: Password to derive key from
        salt: Salt for key derivation (use consistent salt)
        
    Returns:
        Base64-encoded Fernet-compatible key
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,  # OWASP recommended minimum
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key.decode('utf-8')


def re_encrypt_with_new_key(
    ciphertext: str,
    old_key: str,
    new_key: str
) -> str:
    """
    Re-encrypt data with a new key (for key rotation).
    
    Args:
        ciphertext: Data encrypted with old key
        old_key: The old encryption key
        new_key: The new encryption key
        
    Returns:
        Data encrypted with new key
        
    Raises:
        DecryptionError: If decryption with old key fails
        EncryptionError: If encryption with new key fails
    """
    # Decrypt with old key
    old_fernet = Fernet(old_key.encode())
    try:
        plaintext = old_fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise DecryptionError("Failed to decrypt with old key")
    
    # Encrypt with new key
    new_fernet = Fernet(new_key.encode())
    try:
        new_ciphertext = new_fernet.encrypt(plaintext.encode()).decode()
        return new_ciphertext
    except Exception as e:
        raise EncryptionError(f"Failed to encrypt with new key: {e}")


# ==================== AUDIT HELPERS ====================

def log_tfn_access(
    action: str,
    client_id: str,
    user_id: str,
    success: bool,
    reason: Optional[str] = None
):
    """
    Log TFN access for audit purposes.
    
    Args:
        action: Type of access (encrypt, decrypt, view)
        client_id: Client whose TFN was accessed
        user_id: User who performed the action
        success: Whether the action succeeded
        reason: Optional reason for access
    """
    log_data = {
        "event": "tfn_access",
        "action": action,
        "client_id": client_id,
        "user_id": user_id,
        "success": success,
        "reason": reason
    }
    
    if success:
        logger.info(f"TFN access: {action} for client {client_id} by {user_id}")
    else:
        logger.warning(f"TFN access failed: {action} for client {client_id} by {user_id}")
