import subprocess
from .config import KEYCHAIN_SERVICE

def set_secret(account: str, value: str) -> None:
    subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value], check=True, capture_output=True)

def get_secret(account: str) -> str | None:
    result = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def delete_secret(account: str) -> None:
    subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account], capture_output=True)

