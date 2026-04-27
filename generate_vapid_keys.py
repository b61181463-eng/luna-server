import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

private_key = ec.generate_private_key(ec.SECP256R1())
private_numbers = private_key.private_numbers()
private_value = private_numbers.private_value.to_bytes(32, "big")

public_key = private_key.public_key()
public_numbers = public_key.public_numbers()
x = public_numbers.x.to_bytes(32, "big")
y = public_numbers.y.to_bytes(32, "big")
public_value = b"\x04" + x + y

pem = private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()
).decode("utf-8")

print("아래 값을 환경변수에 넣어줘.\n")
print("LUNA_VAPID_PUBLIC_KEY=" + b64url(public_value))
print("LUNA_VAPID_PRIVATE_KEY=" + pem.replace("\n", "\\n"))
print("LUNA_VAPID_SUBJECT=mailto:your-email@example.com")
