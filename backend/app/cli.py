import argparse

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.services.security import encrypt_secret, generate_mfa_secret, hash_password


def create_admin(email: str, password: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(email=email.lower())
            db.add(user)
        secret = generate_mfa_secret()
        user.password_hash = hash_password(password)
        user.email_verified = True
        user.is_admin = True
        user.mfa_secret_encrypted = encrypt_secret(secret)
        user.mfa_enabled = True
        db.commit()
        print("管理者を作成しました。MFAシークレットは今だけ表示されます。")
        print(secret)
        print(pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="棋譜コメント研究所"))


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create-admin")
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.email, args.password)


if __name__ == "__main__":
    main()
