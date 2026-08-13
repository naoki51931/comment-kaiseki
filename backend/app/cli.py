import argparse
from pathlib import Path

import pyotp
from sqlalchemy import select

from app.database import SessionLocal
from app.config import settings
from app.models import User
from app.services.professional_games import import_professional_game_directory
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
    import_games = subcommands.add_parser("import-professional-games")
    import_games.add_argument("directory", type=Path)
    import_games.add_argument("--source-name", required=True)
    import_games.add_argument("--source-reference")
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.email, args.password)
    elif args.command == "import-professional-games":
        with SessionLocal() as db:
            result = import_professional_game_directory(
                db, args.directory, source_name=args.source_name,
                source_reference=args.source_reference,
                max_size_bytes=settings.max_kif_size_bytes,
            )
        print(f"登録: {result.imported}件、登録済み: {result.already_registered}件、無効/読込失敗: {result.invalid}件")


if __name__ == "__main__":
    main()
