"""CLI для запуска сида демо-данных.

Запуск:
    python -m ats.infra.seeds              # стандартный сид
    python -m ats.infra.seeds --dry-run    # только сгенерировать, не записывать
    python -m ats.infra.seeds --seed 123   # другой seed
    python -m ats.infra.seeds --count 100  # 100 кандидатов вместо 5000

УСТОЙЧИВОСТЬ: работает в stub-режиме (генерация в память) и в prod-режиме
(запись в БД через async-session). Если БД недоступна — печатает статистику.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ats.infra.seeds.generator import SeedGenerator
from ats.infra.seeds.settings import SeedSettings


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ats.infra.seeds",
        description="Генерация демо-данных для стенда интеграции ATS Jugo (JUGO-014)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed для генератора (по умолчанию 42)",
    )
    parser.add_argument(
        "--tenants",
        type=int,
        default=None,
        help="Количество тенантов (по умолчанию 3)",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=None,
        help="Кандидатов на тенант (по умолчанию 5000)",
    )
    parser.add_argument(
        "--vacancies",
        type=int,
        default=None,
        help="Вакансий на тенант (по умолчанию 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только сгенерировать, не записывать в БД",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Не очищать таблицы перед сидом",
    )
    return parser.parse_args(argv)


def _build_settings(args: argparse.Namespace) -> SeedSettings:
    """Построить SeedSettings из аргументов CLI."""
    kwargs: dict[str, object] = {}
    if args.seed is not None:
        kwargs["random_seed"] = args.seed
    if args.tenants is not None:
        kwargs["tenant_count"] = args.tenants
    if args.candidates is not None:
        kwargs["candidates_per_tenant"] = args.candidates
    if args.vacancies is not None:
        kwargs["vacancies_per_tenant"] = args.vacancies
    if args.no_truncate:
        kwargs["truncate_before"] = False
    return SeedSettings(**kwargs)


def _print_stats(data: object) -> None:
    """Напечатать статистику сгенерированных данных."""
    print("=== Seed Statistics ===")
    print(f"  Tenants:          {len(data.tenants)}")  # type: ignore[attr-defined]
    print(f"  Roles:            {len(data.roles)}")  # type: ignore[attr-defined]
    print(f"  Users:            {len(data.users)}")  # type: ignore[attr-defined]
    print(f"  Candidates:       {len(data.candidates)}")  # type: ignore[attr-defined]
    print(f"  Vacancies:        {len(data.vacancies)}")  # type: ignore[attr-defined]
    print(f"  Pipeline stages:  {len(data.pipeline_stages)}")  # type: ignore[attr-defined]
    print(f"  Applications:     {len(data.applications)}")  # type: ignore[attr-defined]
    print(f"  Total records:    {data.total_records}")  # type: ignore[attr-defined]
    print("=======================")


async def _run_seed(settings: SeedSettings, dry_run: bool) -> None:
    """Запустить сид: генерация + опциональная запись в БД."""
    print(f"Generating seed data (seed={settings.random_seed})...")
    generator = SeedGenerator(settings)
    data = generator.generate()

    _print_stats(data)

    if dry_run:
        print("Dry run: skipping database write.")
        return

    # Попытка записи в БД (если доступна)
    try:
        await _write_to_db(data, settings)
        print("Seed data written to database.")
    except Exception as exc:
        print(f"Database write skipped (stub mode or DB unavailable): {exc}")


async def _write_to_db(data: object, settings: SeedSettings) -> None:
    """Записать сгенерированные данные в БД."""
    from sqlalchemy import text

    from ats.infra.db.session import get_session_factory

    factory = get_session_factory()

    async with factory() as session:
        if settings.truncate_before:
            # Очистка таблиц (порядок важен из-за FK)
            for table in [
                "applications",
                "pipeline_stages",
                "vacancies",
                "candidates_search",
                "candidates",
                "users",
                "roles",
                "tenants",
            ]:
                await session.execute(text(f"TRUNCATE {table} CASCADE"))

        # Запись тенантов
        for t in data.tenants:  # type: ignore[attr-defined]
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, is_active) "
                    "VALUES (:id, :name, :slug, true)"
                ),
                {"id": str(t.id), "name": t.name, "slug": t.slug},
            )

        # Роли
        for r in data.roles:  # type: ignore[attr-defined]
            await session.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, name, permissions) "
                    "VALUES (:id, :tid, :name, :perms)"
                ),
                {
                    "id": str(r.id),
                    "tid": str(r.tenant_id),
                    "name": r.name,
                    "perms": r.permissions,
                },
            )

        # Пользователи
        for u in data.users:  # type: ignore[attr-defined]
            await session.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, full_name_encrypted, is_active) "
                    "VALUES (:id, :tid, :email, :fname, true)"
                ),
                {
                    "id": str(u.id),
                    "tid": str(u.tenant_id),
                    "email": u.email,
                    "fname": u.full_name,
                },
            )

        await session.commit()

    print(
        f"Written: {len(data.tenants)} tenants, "  # type: ignore[attr-defined]
        f"{len(data.roles)} roles, "  # type: ignore[attr-defined]
        f"{len(data.users)} users"  # type: ignore[attr-defined]
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point для CLI."""
    args = _parse_args(argv)
    settings = _build_settings(args)
    asyncio.run(_run_seed(settings, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
