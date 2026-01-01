"""
Encryption Utilities for Sensitive Data

Provides field-level encryption for sensitive data:
- TFN (Tax File Number)
- ABN (Australian Business Number)
- Bank Account Details (BSB, Account Number)

Uses Fernet symmetric encryption (AES-128-CBC with HMAC) for secure storage.

Environment Variables:
    ENCRYPTION_KEY: Base64-encoded 32-byte key for Fernet encryption
                    Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage:
    from utils.encryption import EncryptionService
    
    # Initialize service
    service = EncryptionService()
    
    # Encrypt sensitive data
    encrypted_tfn = service.encrypt_tfn("123456789")
    encrypted_abn = service.encrypt_abn("51824753556")
    encrypted_bank = service.encrypt_bank_account("123456", "12345678")
    
    # Decrypt when needed
    tfn = service.decrypt_tfn(encrypted_tfn)
    
    # Mask for display (no decryption needed)
    masked = service.mask_tfn("123456789")  # Returns "***456789"

Security Notes:
    - NEVER log plaintext sensitive values
    - Encryption key must be stored securely (Secret Authority)
    - Rotate keys periodically using re-encrypt functionality
    - All sensitive data access should be audited
"""

import os
import re
import json
import base64
import logging
from typing import Optional, Tuple, Dict, Any
from functools import lru_cache
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Environment variable name for encryption key
ENCRYPTION_KEY_ENV = "ENCRYPTION_KEY"

# Salt for key derivation (static for consistency)
KEY_DERIVATION_SALT = b"fdc_tax_core_v1_salt"

# Sensitive field types for audit logging
SENSITIVE_FIELD_TYPES = {
    "tfn": "Tax File Number",
    "abn": "Australian Business Number", 
    "acn": "Australian Company Number",
    "bsb": "Bank State Branch",
    "account_number": "Bank Account Number",
    "bank_details": "Bank Account Details",
}


class EncryptionError(Exception):
    """Base exception for encryption errors"""
    pass


class KeyNotConfiguredError(EncryptionError):
    """Raised when encryption key is not configured"""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails"""
    pass


class ValidationError(EncryptionError):
    """Raised when data validation fails"""
    pass


@dataclass
class EncryptedField:
    """Represents an encrypted field with metadata"""
    ciphertext: str
    field_type: str
    encrypted_at: str
    last_four: Optional[str] = None  # For display purposes


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
        # Log once, not every call (due to caching)
        return None
    
    try:
        # Validate key format
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return fernet
    except Exception as e:
        logger.error(f"Invalid encryption key format: {e}")
        return None


def clear_fernet_cache():
    """Clear the Fernet cache (useful for testing or key rotation)."""
    _get_fernet.cache_clear()


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


# ==================== ENCRYPTION SERVICE CLASS ====================

class EncryptionService:
    """
    Comprehensive encryption service for sensitive data.
    
    Handles encryption/decryption of:
    - TFN (Tax File Number)
    - ABN (Australian Business Number)
    - ACN (Australian Company Number)
    - Bank Details (BSB + Account Number)
    
    Features:
    - Field validation before encryption
    - Masking for safe display
    - Audit logging
    - No plaintext in logs
    """
    
    # Validation patterns
    TFN_PATTERN = re.compile(r'^\d{8,9}$')
    ABN_PATTERN = re.compile(r'^\d{11}$')
    ACN_PATTERN = re.compile(r'^\d{9}$')
    BSB_PATTERN = re.compile(r'^\d{6}$')
    ACCOUNT_PATTERN = re.compile(r'^\d{6,10}$')
    
    def __init__(self):
        """Initialize encryption service."""
        self._fernet = _get_fernet()
    
    @property
    def is_configured(self) -> bool:
        """Check if encryption is configured."""
        return self._fernet is not None
    
    def _encrypt(self, plaintext: str) -> str:
        """Internal encryption method."""
        if not self._fernet:
            raise KeyNotConfiguredError("ENCRYPTION_KEY not configured")
        
        return self._fernet.encrypt(plaintext.encode('utf-8')).decode('utf-8')
    
    def _decrypt(self, ciphertext: str) -> str:
        """Internal decryption method."""
        if not self._fernet:
            raise KeyNotConfiguredError("ENCRYPTION_KEY not configured")
        
        try:
            return self._fernet.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            raise DecryptionError("Invalid encryption token - data may be corrupted or key mismatch")
    
    # ==================== TFN OPERATIONS ====================
    
    def encrypt_tfn(self, tfn: str, validate: bool = True) -> str:
        """
        Encrypt a Tax File Number.
        
        Args:
            tfn: 8-9 digit TFN
            validate: Whether to validate format
            
        Returns:
            Encrypted TFN string
        """
        if not tfn:
            raise ValidationError("TFN cannot be empty")
        
        # Clean the input
        cleaned = re.sub(r'[\s\-]', '', tfn)
        
        if validate and not self.TFN_PATTERN.match(cleaned):
            raise ValidationError("TFN must be 8-9 digits")
        
        # SECURITY: Never log the actual TFN
        logger.debug(f"Encrypting TFN (last 4: ***{cleaned[-4:]})")
        
        return self._encrypt(cleaned)
    
    def decrypt_tfn(self, ciphertext: str) -> str:
        """
        Decrypt a Tax File Number.
        
        Args:
            ciphertext: Encrypted TFN
            
        Returns:
            Decrypted TFN string
        """
        if not ciphertext:
            raise ValidationError("Ciphertext cannot be empty")
        
        result = self._decrypt(ciphertext)
        
        # SECURITY: Never log the actual TFN
        logger.debug(f"Decrypted TFN (last 4: ***{result[-4:]})")
        
        return result
    
    def mask_tfn(self, tfn: str, visible: int = 4) -> str:
        """
        Mask TFN for safe display.
        
        Args:
            tfn: Plain or partial TFN
            visible: Number of digits to show
            
        Returns:
            Masked string (e.g., "*****6789")
        """
        if not tfn:
            return ""
        
        cleaned = re.sub(r'[\s\-]', '', tfn)
        
        if len(cleaned) <= visible:
            return cleaned
        
        return '*' * (len(cleaned) - visible) + cleaned[-visible:]
    
    # ==================== ABN OPERATIONS ====================
    
    def encrypt_abn(self, abn: str, validate: bool = True) -> str:
        """
        Encrypt an Australian Business Number.
        
        Args:
            abn: 11 digit ABN
            validate: Whether to validate format and checksum
            
        Returns:
            Encrypted ABN string
        """
        if not abn:
            raise ValidationError("ABN cannot be empty")
        
        cleaned = re.sub(r'[\s\-]', '', abn)
        
        if validate:
            if not self.ABN_PATTERN.match(cleaned):
                raise ValidationError("ABN must be exactly 11 digits")
            
            # ABN checksum validation
            if not self._validate_abn_checksum(cleaned):
                raise ValidationError("Invalid ABN checksum")
        
        logger.debug(f"Encrypting ABN (last 4: ***{cleaned[-4:]})")
        
        return self._encrypt(cleaned)
    
    def decrypt_abn(self, ciphertext: str) -> str:
        """Decrypt an Australian Business Number."""
        if not ciphertext:
            raise ValidationError("Ciphertext cannot be empty")
        
        result = self._decrypt(ciphertext)
        logger.debug(f"Decrypted ABN (last 4: ***{result[-4:]})")
        
        return result
    
    def mask_abn(self, abn: str, visible: int = 4) -> str:
        """Mask ABN for safe display."""
        if not abn:
            return ""
        
        cleaned = re.sub(r'[\s\-]', '', abn)
        
        if len(cleaned) <= visible:
            return cleaned
        
        return '*' * (len(cleaned) - visible) + cleaned[-visible:]
    
    def _validate_abn_checksum(self, abn: str) -> bool:
        """Validate ABN using weighted modulus algorithm."""
        try:
            weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
            digits = [int(d) for d in abn]
            digits[0] -= 1  # Subtract 1 from first digit
            
            checksum = sum(d * w for d, w in zip(digits, weights))
            return checksum % 89 == 0
        except (ValueError, IndexError):
            return False
    
    # ==================== ACN OPERATIONS ====================
    
    def encrypt_acn(self, acn: str, validate: bool = True) -> str:
        """
        Encrypt an Australian Company Number.
        
        Args:
            acn: 9 digit ACN
            validate: Whether to validate format
            
        Returns:
            Encrypted ACN string
        """
        if not acn:
            raise ValidationError("ACN cannot be empty")
        
        cleaned = re.sub(r'[\s\-]', '', acn)
        
        if validate and not self.ACN_PATTERN.match(cleaned):
            raise ValidationError("ACN must be exactly 9 digits")
        
        logger.debug(f"Encrypting ACN (last 4: ***{cleaned[-4:]})")
        
        return self._encrypt(cleaned)
    
    def decrypt_acn(self, ciphertext: str) -> str:
        """Decrypt an Australian Company Number."""
        if not ciphertext:
            raise ValidationError("Ciphertext cannot be empty")
        
        result = self._decrypt(ciphertext)
        logger.debug(f"Decrypted ACN (last 4: ***{result[-4:]})")
        
        return result
    
    def mask_acn(self, acn: str, visible: int = 4) -> str:
        """Mask ACN for safe display."""
        if not acn:
            return ""
        
        cleaned = re.sub(r'[\s\-]', '', acn)
        
        if len(cleaned) <= visible:
            return cleaned
        
        return '*' * (len(cleaned) - visible) + cleaned[-visible:]
    
    # ==================== BANK DETAILS OPERATIONS ====================
    
    def encrypt_bank_account(
        self, 
        bsb: str, 
        account_number: str,
        validate: bool = True
    ) -> str:
        """
        Encrypt bank account details.
        
        Args:
            bsb: 6 digit BSB
            account_number: 6-10 digit account number
            validate: Whether to validate format
            
        Returns:
            Encrypted JSON string containing both values
        """
        if not bsb or not account_number:
            raise ValidationError("BSB and account number are required")
        
        clean_bsb = re.sub(r'[\s\-]', '', bsb)
        clean_account = re.sub(r'[\s\-]', '', account_number)
        
        if validate:
            if not self.BSB_PATTERN.match(clean_bsb):
                raise ValidationError("BSB must be exactly 6 digits")
            if not self.ACCOUNT_PATTERN.match(clean_account):
                raise ValidationError("Account number must be 6-10 digits")
        
        # Combine into JSON for structured storage
        bank_data = json.dumps({
            "bsb": clean_bsb,
            "account": clean_account
        })
        
        logger.debug(f"Encrypting bank details (BSB: ***{clean_bsb[-3:]}, Acc: ***{clean_account[-4:]})")
        
        return self._encrypt(bank_data)
    
    def decrypt_bank_account(self, ciphertext: str) -> Dict[str, str]:
        """
        Decrypt bank account details.
        
        Returns:
            Dict with 'bsb' and 'account' keys
        """
        if not ciphertext:
            raise ValidationError("Ciphertext cannot be empty")
        
        decrypted = self._decrypt(ciphertext)
        
        try:
            data = json.loads(decrypted)
            logger.debug(f"Decrypted bank details (BSB: ***{data['bsb'][-3:]}, Acc: ***{data['account'][-4:]})")
            return data
        except json.JSONDecodeError:
            raise DecryptionError("Invalid bank details format")
    
    def mask_bsb(self, bsb: str) -> str:
        """Mask BSB for safe display (format: ***-456)."""
        if not bsb:
            return ""
        
        cleaned = re.sub(r'[\s\-]', '', bsb)
        
        if len(cleaned) <= 3:
            return cleaned
        
        return '***-' + cleaned[-3:]
    
    def mask_account_number(self, account: str, visible: int = 4) -> str:
        """Mask account number for safe display."""
        if not account:
            return ""
        
        cleaned = re.sub(r'[\s\-]', '', account)
        
        if len(cleaned) <= visible:
            return cleaned
        
        return '*' * (len(cleaned) - visible) + cleaned[-visible:]
    
    # ==================== GENERIC FIELD OPERATIONS ====================
    
    def encrypt_field(self, value: str, field_type: str = "generic") -> EncryptedField:
        """
        Encrypt any sensitive field with metadata.
        
        Args:
            value: Value to encrypt
            field_type: Type of field for audit logging
            
        Returns:
            EncryptedField with ciphertext and metadata
        """
        if not value:
            raise ValidationError("Value cannot be empty")
        
        logger.debug(f"Encrypting {field_type} field")
        
        ciphertext = self._encrypt(value)
        last_four = value[-4:] if len(value) >= 4 else None
        
        return EncryptedField(
            ciphertext=ciphertext,
            field_type=field_type,
            encrypted_at=datetime.now(timezone.utc).isoformat(),
            last_four=last_four
        )
    
    def decrypt_field(self, ciphertext: str, field_type: str = "generic") -> str:
        """
        Decrypt any sensitive field.
        
        Args:
            ciphertext: Encrypted value
            field_type: Type of field for audit logging
            
        Returns:
            Decrypted string
        """
        if not ciphertext:
            raise ValidationError("Ciphertext cannot be empty")
        
        result = self._decrypt(ciphertext)
        logger.debug(f"Decrypted {field_type} field")
        
        return result
    
    # ==================== BATCH OPERATIONS ====================
    
    def encrypt_client_sensitive_data(
        self,
        tfn: Optional[str] = None,
        abn: Optional[str] = None,
        acn: Optional[str] = None,
        bsb: Optional[str] = None,
        account_number: Optional[str] = None,
        validate: bool = True
    ) -> Dict[str, Optional[str]]:
        """
        Encrypt all sensitive fields for a client profile.
        
        Returns dict with encrypted values (None if input was None).
        """
        result = {}
        
        if tfn:
            result['tfn_encrypted'] = self.encrypt_tfn(tfn, validate)
            result['tfn_last_four'] = tfn[-4:] if len(tfn) >= 4 else None
        else:
            result['tfn_encrypted'] = None
            result['tfn_last_four'] = None
        
        if abn:
            result['abn_encrypted'] = self.encrypt_abn(abn, validate)
        else:
            result['abn_encrypted'] = None
        
        if acn:
            result['acn_encrypted'] = self.encrypt_acn(acn, validate)
        else:
            result['acn_encrypted'] = None
        
        if bsb and account_number:
            result['bank_encrypted'] = self.encrypt_bank_account(bsb, account_number, validate)
        else:
            result['bank_encrypted'] = None
        
        return result
    
    def decrypt_client_sensitive_data(
        self,
        tfn_encrypted: Optional[str] = None,
        abn_encrypted: Optional[str] = None,
        acn_encrypted: Optional[str] = None,
        bank_encrypted: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Decrypt all sensitive fields for a client profile.
        
        Returns dict with decrypted values.
        """
        result = {}
        
        if tfn_encrypted:
            result['tfn'] = self.decrypt_tfn(tfn_encrypted)
        
        if abn_encrypted:
            result['abn'] = self.decrypt_abn(abn_encrypted)
        
        if acn_encrypted:
            result['acn'] = self.decrypt_acn(acn_encrypted)
        
        if bank_encrypted:
            bank_data = self.decrypt_bank_account(bank_encrypted)
            result['bsb'] = bank_data['bsb']
            result['account_number'] = bank_data['account']
        
        return result


# ==================== AUDIT LOGGING ====================

def log_sensitive_access(
    field_type: str,
    action: str,
    entity_id: str,
    user_id: str,
    success: bool,
    reason: Optional[str] = None
):
    """
    Log access to sensitive data for audit purposes.
    
    SECURITY: Never logs actual sensitive values.
    
    Args:
        field_type: Type of field (tfn, abn, bank_details, etc.)
        action: Type of access (encrypt, decrypt, view, update)
        entity_id: ID of entity (client, profile, etc.)
        user_id: User who performed the action
        success: Whether the action succeeded
        reason: Optional reason for access
    """
    field_name = SENSITIVE_FIELD_TYPES.get(field_type, field_type)
    
    # Structured log for audit trail
    log_entry = {
        "event": "sensitive_data_access",
        "field_type": field_type,
        "field_name": field_name,
        "action": action,
        "entity_id": entity_id,
        "user_id": user_id,
        "success": success,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if success:
        logger.info(
            f"Sensitive data access: {action} {field_name} for entity {entity_id} by {user_id}",
            extra=log_entry
        )
    else:
        logger.warning(
            f"Sensitive data access FAILED: {action} {field_name} for entity {entity_id} by {user_id}",
            extra=log_entry
        )


# ==================== MODULE-LEVEL CONVENIENCE FUNCTIONS ====================
# (Keep existing functions for backwards compatibility)

