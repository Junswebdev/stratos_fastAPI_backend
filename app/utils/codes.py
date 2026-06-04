import string
import secrets

def generate_join_code(length: int = 6) -> str:
    """
    Generate a random alphanumeric join code.
    """
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))
