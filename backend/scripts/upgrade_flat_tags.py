"""MySQL-only, backup-first upgrade with isolated recovery/migration rehearsal.

Run --rehearse first; --apply --backup-dir <printed path> uses that exact verified
backup. Stop API/Worker writes before either operation. Passwords are passed only
via child process environment, never command arguments or the manifest.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_db_url, runtime_config_path
from app.db.migrations import _alembic_config

LEGACY = {"alembic_version", "paper_templates", "exam_paper_batches", "exam_papers", "exam_paper_items",
          "question_categories", "categories", "category_dimensions", "question_types"}


def digest(rows):
    encoded = sorted(json.dumps(dict(row), sort_keys=True, ensure_ascii=False, default=str) for row in rows)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def engine_for(url):
    return create_engine(url.set(drivername="mysql+pymysql"), pool_pre_ping=True, hide_parameters=True)


def baseline(url):
    engine = engine_for(url)
    report = {}
    try:
        with engine.connect() as conn:
            schema = inspect(conn)
            for table in sorted(set(schema.get_table_names()) - LEGACY):
                columns = [c["name"] for c in schema.get_columns(table) if not (table == "questions" and c["name"] == "question_type_id")]
                primary = schema.get_pk_constraint(table)["constrained_columns"]
                sql = "SELECT " + ",".join(f"`{c}`" for c in columns) + f" FROM `{table}`"
                rows = list(conn.execute(text(sql)).mappings())
                report[table] = {"columns": columns, "pk": primary, "keys": [[row[c] for c in primary] for row in rows],
                                 "count": len(rows), "sha256": digest(rows)}
        return report
    finally:
        engine.dispose()


def verify(url, expected):
    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            for table, item in expected.items():
                cols = ",".join(f"`{c}`" for c in item["columns"])
                rows = list(conn.execute(text(f"SELECT {cols} FROM `{table}`")).mappings())
                if item["pk"]:
                    old_keys = {tuple(key) for key in item["keys"]}
                    rows = [row for row in rows if tuple(row[c] for c in item["pk"]) in old_keys]
                if len(rows) != item["count"] or digest(rows) != item["sha256"]:
                    raise RuntimeError(f"Data preservation check failed: {table}")
    finally:
        engine.dispose()


def client_args(url):
    return [f"--host={url.host or 'localhost'}", f"--port={url.port or 3306}", f"--user={url.username}", "--default-character-set=utf8mb4"]


def mysql_program(name):
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required MySQL utility unavailable: {name}")
    return executable


def mysql_io(url, file, *, dump=False):
    env = os.environ.copy()
    env["MYSQL_PWD"] = url.password or ""
    args = client_args(url)
    if dump:
        args += ["--single-transaction", "--routines", "--triggers", "--hex-blob", "--set-gtid-purged=OFF", "--no-tablespaces", url.database]
        with file.open("wb") as stream:
            result = subprocess.run([mysql_program("mysqldump"), *args], stdout=stream, stderr=subprocess.PIPE, env=env)
    else:
        with file.open("rb") as stream:
            result = subprocess.run([mysql_program("mysql"), *args, url.database], stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if result.returncode:
        raise RuntimeError("MySQL backup/restore failed: " + result.stderr.decode(errors="replace").replace(url.password or "<absent>", "***"))


def create_database(url, name):
    if not re.fullmatch(r"qb_flat_v2_[a-z0-9_]+", name) or name == url.database:
        raise ValueError("Only dedicated qb_flat_v2_* rehearsal databases may be created")
    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    finally:
        engine.dispose()
    return url.set(database=name)


def drop_rehearsal(url, original):
    name = url.database
    if not name.startswith("qb_flat_v2_") or name == original.database:
        raise ValueError("Refusing to remove a non-rehearsal database")
    engine = engine_for(original)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP DATABASE `{name}`"))
    finally:
        engine.dispose()


def migrate(url, *, maintenance=False, revision="head", drift=True):
    cfg = _alembic_config(url.render_as_string(hide_password=False))
    cfg.attributes["flat_tags_maintenance"] = maintenance
    command.upgrade(cfg, revision)
    if drift:
        command.check(cfg)


async def seed(url):
    from sqlalchemy import select
    from app.models.subject import Subject
    from scripts.seed_flat_tags_v2 import seed_subject
    engine = create_async_engine(url, hide_parameters=True)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            for subject in (await db.execute(select(Subject))).scalars():
                await seed_subject(db, subject)
            await db.commit()
    finally:
        await engine.dispose()


def counts(url):
    engine = engine_for(url)
    try:
        with engine.connect() as conn:
            return {**{table: conn.execute(text(f"SELECT count(*) FROM `{table}`")).scalar_one()
                       for table in ("questions", "user", "subjects", "tags", "paper_templates", "exam_papers")},
                    "revision": conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()}
    finally:
        engine.dispose()


def write_manifest(folder, report):
    (folder / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def rehearse(url):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = BACKEND / "backups" / "flat-tags-v2" / stamp
    folder.mkdir(parents=True, exist_ok=False)
    report = {"created_at": stamp, "host": url.host, "database": url.database,
              "before": counts(url), "baseline": baseline(url), "rehearsal_complete": False}
    write_manifest(folder, report)
    backup = folder / "database.sql"
    mysql_io(url, backup, dump=True)
    report["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    for source in (BACKEND / ".env", runtime_config_path()):
        if source.exists():
            shutil.copy2(source, folder / ("runtime-config.json" if source.name == "config.json" else source.name))
    write_manifest(folder, report)
    created = []
    try:
        restored = create_database(url, "qb_flat_v2_restore_" + stamp); created.append(restored)
        mysql_io(restored, backup)
        verify(restored, report["baseline"])
        report["restore_verified"] = True
        if report["before"]["revision"] == "f7a8b9c0d1e2" and report["before"]["paper_templates"]:
            try:
                migrate(restored)
            except RuntimeError as exc:
                if "旧模板需要维护升级" not in str(exc):
                    raise
                report["legacy_startup_gate_verified"] = True
            else:
                raise RuntimeError("Legacy maintenance gate failed")
        migrate(restored, maintenance=True)
        asyncio.run(seed(restored)); asyncio.run(seed(restored))
        verify(restored, report["baseline"])
        report["upgraded_clone"] = counts(restored)
        from scripts.accept_flat_tags_v2 import acceptance
        report["acceptance"] = asyncio.run(acceptance(restored, folder / "rehearsal-acceptance"))
        verify(restored, report["baseline"])
        empty = create_database(url, "qb_flat_v2_empty_" + stamp); created.append(empty)
        migrate(empty)
        report["empty_install_verified"] = True
        report["rehearsal_complete"] = True
    finally:
        write_manifest(folder, report)
        for test_url in reversed(created):
            drop_rehearsal(test_url, url)
    print(json.dumps({"backup_dir": str(folder), "before": report["before"], "rehearsal_complete": report["rehearsal_complete"]}, ensure_ascii=False))


def apply(url, folder):
    report = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if not report.get("rehearsal_complete") or report["database"] != url.database or report["host"] != url.host:
        raise RuntimeError("A completed rehearsal for this exact server/database is required")
    backup = folder / "database.sql"
    if hashlib.sha256(backup.read_bytes()).hexdigest() != report["backup_sha256"]:
        raise RuntimeError("Backup checksum mismatch")
    if baseline(url) != report["baseline"] or counts(url) != report["before"]:
        raise RuntimeError("Database changed since backup; stop writes and repeat rehearsal")
    try:
        migrate(url, maintenance=True)
        asyncio.run(seed(url))
        verify(url, report["baseline"])
        report["after"] = counts(url)
        report["applied"] = True
    except Exception:
        # MySQL DDL is not transactional. Keep services stopped; restore exact
        # backup into a clean database with --restore if any phase fails.
        report["applied"] = False
        report["recovery_required"] = True
        raise
    finally:
        write_manifest(folder, report)
    print(json.dumps({"backup_dir": str(folder), "after": report["after"], "original_data_verified": True}, ensure_ascii=False))


def restore(url, folder):
    report = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if report["database"] != url.database or report["host"] != url.host:
        raise RuntimeError("Backup belongs to a different database")
    file = folder / "database.sql"
    if hashlib.sha256(file.read_bytes()).hexdigest() != report["backup_sha256"]:
        raise RuntimeError("Backup checksum mismatch")
    engine = engine_for(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for table in inspect(conn).get_table_names():
                conn.execute(text(f"DROP TABLE `{table}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    finally:
        engine.dispose()
    mysql_io(url, file)
    verify(url, report["baseline"])
    if counts(url) != report["before"]:
        raise RuntimeError("Restored database counts differ")
    report["restored"] = True
    write_manifest(folder, report)
    print("Original database restored and verified; start only the pre-upgrade application.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--rehearse", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--restore", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    os.chdir(BACKEND)
    url = make_url(get_db_url())
    if url.get_backend_name() != "mysql":
        parser.error("This maintenance workflow supports MySQL only")
    if args.rehearse:
        rehearse(url)
    elif not args.backup_dir:
        parser.error("--backup-dir is required for apply/restore")
    elif args.apply:
        apply(url, args.backup_dir.resolve())
    else:
        restore(url, args.backup_dir.resolve())


if __name__ == "__main__":
    main()
