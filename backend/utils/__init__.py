"""
Utils Package

Provides utility modules for:
- encryption: Field-level encryption for sensitive data (TFN, etc.)
"""

from .encryption import (
    encrypt_tfn,
    decrypt_tfn,
    mask_tfn,
    get_tfn_last_four,
    encrypt_sensitive_field,
    decrypt_sensitive_field,
    generate_encryption_key,
    is_encryption_configured,
    EncryptionError,
    DecryptionError,
    KeyNotConfiguredError,
)

__all__ = [
    'encrypt_tfn',
    'decrypt_tfn',
    'mask_tfn',
    'get_tfn_last_four',
    'encrypt_sensitive_field',
    'decrypt_sensitive_field',
    'generate_encryption_key',
    'is_encryption_configured',
    'EncryptionError',
    'DecryptionError',
    'KeyNotConfiguredError',
]
