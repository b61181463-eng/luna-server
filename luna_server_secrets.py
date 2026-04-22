import keyring

SERVICE_NAME = "luna_server"

def save_secret(site_key: str, username: str, password: str) -> None:
    keyring.set_password(SERVICE_NAME, f"{site_key}:username", username)
    keyring.set_password(SERVICE_NAME, f"{site_key}:password", password)

def load_secret(site_key: str):
    username = keyring.get_password(SERVICE_NAME, f"{site_key}:username")
    password = keyring.get_password(SERVICE_NAME, f"{site_key}:password")
    return username, password

def delete_secret(site_key: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, f"{site_key}:username")
    except Exception:
        pass
    try:
        keyring.delete_password(SERVICE_NAME, f"{site_key}:password")
    except Exception:
        pass