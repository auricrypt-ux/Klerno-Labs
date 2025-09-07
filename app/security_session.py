import os, time, jwt
from passlib.hash import bcrypt

JWT_SECRET = os.getenv("JWT_SECRET", "dev_insecure_change_me")
JWT_ALG    = "HS256"
JWT_AGE    = 60*60*24*7   # 7 days

def hash_pw(pw: str) -> str:
    return bcrypt.hash(pw)

def verify_pw(pw: str, hashed: str) -> bool:
    return bcrypt.verify(pw, hashed)

def issue_jwt(user_id: int, email: str, role: str):
    now = int(time.time())
    payload = {"sub": str(user_id), "email": email, "role": role, "iat": now, "exp": now+JWT_AGE}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def decode_jwt(token: str):
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
