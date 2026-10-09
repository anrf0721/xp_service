"""Local configuration and one-service launcher. Never prints credentials."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("owner", "procedure", "ai", "account")


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.startswith("#"):
                continue
            key, value = raw.split("=", 1)
            os.environ.setdefault(key, value)
    for name in SERVICES:
        key = "XP_" + name.upper() + "_DATABASE_URL"
        if key not in os.environ:
            os.environ[key] = URL.create("postgresql+psycopg", username=os.environ["XP_PG_USER"],
                password=os.environ["XP_PG_PASSWORD"], host=os.environ["XP_PG_HOST"],
                port=int(os.environ.get("XP_PG_PORT", "5432")), database="xp_" + name).render_as_string(hide_password=False)


def configure():
    path = ROOT / ".env"
    if path.exists():
        raise RuntimeError("Local .env already exists; refusing to replace it")
    values = {key: os.environ[key] for key in ("XP_PG_HOST", "XP_PG_USER", "XP_PG_PASSWORD")}
    values["XP_PG_PORT"] = os.environ.get("XP_PG_PORT", "5432")
    for key in ("XP_INTERNAL_SERVICE_TOKEN", "XP_OWNER_SECRET", "XP_AUTHORIZED_USER_SECRET", "XP_ADVISOR_SECRET"):
        values[key] = secrets.token_urlsafe(32)
    if any("\n" in value or "\r" in value for value in values.values()):
        raise RuntimeError("Configuration values must fit on one line")
    path.write_text("# Local secrets; excluded from version control.\n" + "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    print("Created local .env with random credential and internal secrets; contents not printed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("configure", "initialize", "serve", "test"))
    parser.add_argument("service", nargs="?", choices=SERVICES)
    args = parser.parse_args()
    if args.action == "configure":
        configure()
        return 0
    load_env()
    if args.action == "initialize":
        for name in SERVICES:
            subprocess.run([sys.executable, "-m", "xp_" + name + "_service", "--initialize"], cwd=ROOT, check=True)
        print("Initialized four dedicated production databases")
    elif args.action == "serve":
        if args.service is None:
            parser.error("serve requires a service name")
        os.execv(sys.executable, [sys.executable, "-m", "xp_" + args.service + "_service"])
    elif args.action == "test":
        # Test runner never receives the production database URLs.
        for name in SERVICES:
            os.environ.pop("XP_" + name.upper() + "_DATABASE_URL", None)
        subprocess.run([sys.executable, "tests/integration.py"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, RuntimeError, subprocess.CalledProcessError):
        print("Command failed; check configuration and service artifact logs (secrets not printed)", file=sys.stderr)
        raise SystemExit(1) from None
