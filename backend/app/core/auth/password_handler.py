"""
Password hashing and verification using bcrypt.

Why bcrypt over MD5/SHA?
    MD5/SHA are fast — designed for checksums, not passwords.
    A GPU can compute 10 billion MD5 hashes/second.
    bcrypt is slow by design — ~100ms per hash at rounds=12.
    This makes brute-force attacks impractical.

Why not Argon2?
    Argon2 is the modern winner of the Password Hashing Competition.
    bcrypt is used here because passlib[bcrypt] is already in our
    requirements and is battle-tested. Argon2 can be swapped in later.

Salt:
    bcrypt automatically generates a unique random salt per hash.
    Two identical passwords produce completely different hashes.
    Salt is embedded in the hash string — no separate storage needed.

Hash format:
    $2b$12$<22-char-salt><31-char-hash>
    $2b = bcrypt version
    $12 = work factor (rounds)
"""

from passlib.context import CryptContext

from app.utils.logger import get_logger

logger = get_logger(__name__)

# CryptContext manages multiple hashing schemes.
# 'bcrypt' is the primary scheme.
# deprecated='auto' means old hashes are automatically upgraded on next login.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # 12 rounds = ~250ms on modern hardware
)


def hash_password(plaintext: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    The salt is automatically generated and embedded in the result.
    Never store the plaintext — only store the returned hash.

    Args:
        plaintext: The user's raw password from the registration form.

    Returns:
        bcrypt hash string (60 chars). Store this in the database.

    Example:
        hashed = hash_password("my_secure_password")
        # Store hashed in users.password_hash
        # "$2b$12$randomsalt...hashedvalue..."
    """
    if not plaintext:
        raise ValueError("Password cannot be empty")

    if len(plaintext) < 8:
        raise ValueError("Password must be at least 8 characters")

    hashed = pwd_context.hash(plaintext)

    logger.debug("password_hashed")  # Never log the plaintext or hash
    return hashed


def verify_password(plaintext: str, hashed: str) -> bool:
    """
    Verify a plaintext password against its bcrypt hash.

    Extracts the salt from the hash, re-hashes the plaintext
    with that salt, and compares the results in constant time.

    Constant-time comparison prevents timing attacks — an attacker
    cannot determine how many characters matched by measuring
    how long the comparison took.

    Args:
        plaintext: The password the user typed at login.
        hashed:    The bcrypt hash stored in the database.

    Returns:
        True if the password matches, False otherwise.
        Never raises — returns False on any error.

    Example:
        is_valid = verify_password("my_secure_password", stored_hash)
        if not is_valid:
            return error_response("Invalid credentials")
    """
    if not plaintext or not hashed:
        return False

    try:
        result = pwd_context.verify(plaintext, hashed)
        logger.debug("password_verified", match=result)
        return result
    except Exception as e:
        # Log but never expose the reason for failure
        logger.warning("password_verification_error", error=str(e))
        return False


def needs_rehash(hashed: str) -> bool:
    """
    Check if a stored hash should be upgraded.

    Returns True if the hash was created with fewer rounds than
    the current setting. Call this after a successful login and
    update the stored hash if True.

    This allows gradual hash upgrades as you increase bcrypt rounds
    over time without forcing all users to change passwords.

    Args:
        hashed: The bcrypt hash stored in the database.

    Returns:
        True if the hash should be recomputed with current settings.
    """
    return pwd_context.needs_update(hashed)


def validate_password_strength(password: str) -> list[str]:
    """
    Validate password strength and return list of violations.

    Returns empty list if password meets all requirements.
    Returns list of human-readable error messages if not.

    Args:
        password: The candidate password to validate.

    Returns:
        List of violation strings. Empty = password is acceptable.

    Example:
        errors = validate_password_strength("weak")
        # ["Password must be at least 8 characters",
        #  "Password must contain at least one number"]
    """
    errors = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters")

    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")

    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")

    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")

    return errors