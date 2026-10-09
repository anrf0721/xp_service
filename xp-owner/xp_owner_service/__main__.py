import argparse
import os

import uvicorn

from xp_owner_service.infrastructure.database import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    if args.initialize:
        initialize()
    else:
        uvicorn.run("xp_owner_service.app.main:app", host=os.environ.get("XP_BIND_HOST", "127.0.0.1"), port=8000, access_log=False)


if __name__ == "__main__":
    main()
