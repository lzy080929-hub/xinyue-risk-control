"""Create a Werkzeug password hash for ADMIN_PASSWORD_HASH.

Usage:
    ./.venv/Scripts/python.exe scripts/hash_admin_password.py

The password is read without echo, must be typed twice, and is never written
to disk or printed. Paste only the resulting hash into .env or the deployment
platform's secret settings.
"""

from __future__ import annotations

import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> int:
    password = getpass.getpass("管理员密码（输入时不显示）：")
    if len(password) < 12:
        print("密码至少需要 12 个字符。", file=sys.stderr)
        return 1
    confirmation = getpass.getpass("再次输入管理员密码：")
    if password != confirmation:
        print("两次输入不一致，未生成哈希。", file=sys.stderr)
        return 1

    print("\nADMIN_PASSWORD_HASH（只复制这一行等号后面的内容）：")
    print(f"ADMIN_PASSWORD_HASH={generate_password_hash(password)}")
    print("\n请同时设置一个不易猜中的 ADMIN_USERNAME。不要保存明文密码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
