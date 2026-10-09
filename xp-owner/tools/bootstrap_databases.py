"""Create only absent, allowlisted databases from the postgres maintenance DB."""
import argparse
import os

import psycopg
from psycopg import sql


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-production", action="store_true")
    args = parser.parse_args()
    names = ["xp_owner_test", "xp_procedure_test", "xp_ai_test", "xp_account_test"]
    if args.include_production:
        names += ["xp_owner", "xp_procedure", "xp_ai", "xp_account"]
    with psycopg.connect(host=os.environ["XP_PG_HOST"], port=int(os.environ.get("XP_PG_PORT", "5432")),
        dbname="postgres", user=os.environ["XP_PG_USER"], password=os.environ["XP_PG_PASSWORD"],
        connect_timeout=8, autocommit=True) as conn:
        for name in names:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            if exists:
                print("EXISTS", name)
            else:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                print("CREATED", name)


if __name__ == "__main__":
    main()
