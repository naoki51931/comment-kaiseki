from email.message import EmailMessage
import smtplib

from app.config import settings


def send_verification_email(to_email: str, verification_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "【棋譜コメント研究所】メールアドレスを確認してください"
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(
        "棋譜コメント研究所への登録ありがとうございます。\n"
        "次のURLを24時間以内に開いてメールアドレスを確認してください。\n\n"
        f"{verification_url}\n\n"
        "心当たりがない場合は、このメールを破棄してください。"
    )
    send_email_message(message)


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "【棋譜コメント研究所】パスワード再設定"
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(
        "パスワードの再設定を受け付けました。\n"
        "次のURLを1時間以内に開いて、新しいパスワードを登録してください。\n\n"
        f"{reset_url}\n\n"
        "心当たりがない場合は、このメールを破棄してください。パスワードは変更されません。"
    )
    send_email_message(message)


def send_email_message(message: EmailMessage) -> None:
    if not settings.email_delivery_enabled:
        return
    if settings.smtp_starttls and settings.smtp_ssl:
        raise RuntimeError("SMTP_STARTTLSとSMTP_SSLは同時に有効化できません。")
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        if settings.smtp_username or settings.smtp_password:
            if not settings.smtp_username or not settings.smtp_password:
                raise RuntimeError("SMTP_USERNAMEとSMTP_PASSWORDは両方設定してください。")
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
