#!/usr/bin/env python3
"""
Set or change the LAN Tracker admin password.
Usage: python3 /opt/lan-tracker/scripts/set-password.py
"""
import bcrypt
import getpass
import re
import sys

CONFIG_FILE = "/etc/lan-tracker/lan-tracker.conf"


def update_config(key: str, value: str):
    with open(CONFIG_FILE, "r") as f:
        content = f.read()
    pattern = rf"^{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{key}={value}\n"
    with open(CONFIG_FILE, "w") as f:
        f.write(content)


def main():
    print("LAN Tracker — Set Admin Password")
    print("-" * 35)
    pw = getpass.getpass("New password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        print("Passwords do not match.")
        sys.exit(1)
    if len(pw) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)
    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    update_config("LT_ADMIN_HASH", hashed)
    update_config("LT_AUTH_ENABLED", "true")
    print("\nPassword set successfully.")
    print("Restart the service:  systemctl restart lan-tracker")


if __name__ == "__main__":
    main()
