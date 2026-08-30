"""Тесты сида демо-данных (JUGO-014).

Проверяют:
- SeedSettings (env: ATS_SEED_*)
- Детерминированность генератора (одинаковый seed → одинаковые данные)
- Количество генерируемых сущностей
- Мульти-тенантность (2-3 тенанта с разными slug)
- Роли: 6 системных ролей на тенант
- Пользователи: по одному на роль
- Кандидаты: правильное количество + валидные данные
- Вакансии: 20 на тенант + role_description + requirements
- Стадии пайплайна: 8 на вакансию
- Отклики: applications ссылаются на существующих кандидатов/вакансии
- CLI: парсинг аргументов
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ats.infra.seeds.generator import SeedGenerator
from ats.infra.seeds.settings import SeedSettings

# ──────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────


class TestSeedSettings:
    def test_defaults(self) -> None:
        s = SeedSettings()
        assert s.random_seed == 42
        assert s.tenant_count == 3
        assert s.candidates_per_tenant == 5000
        assert s.vacancies_per_tenant == 20
        assert s.application_probability == 0.35
        assert s.max_applications_per_candidate == 3
        assert s.truncate_before is True


# ──────────────────────────────────────────────────────────────
# Детерминированность
# ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_seed_same_data(self) -> None:
        """Одинаковый seed → одинаковые данные (воспроизводимость)."""
        settings = SeedSettings(random_seed=42, candidates_per_tenant=50)
        gen1 = SeedGenerator(settings)
        gen2 = SeedGenerator(settings)
        data1 = gen1.generate()
        data2 = gen2.generate()

        # Сравниваем ФИО кандидатов
        names1 = [c.full_name for c in data1.candidates]
        names2 = [c.full_name for c in data2.candidates]
        assert names1 == names2

    def test_different_seed_different_data(self) -> None:
        """Разный seed → разные данные."""
        settings1 = SeedSettings(random_seed=42, candidates_per_tenant=50)
        settings2 = SeedSettings(random_seed=999, candidates_per_tenant=50)
        gen1 = SeedGenerator(settings1)
        gen2 = SeedGenerator(settings2)
        data1 = gen1.generate()
        data2 = gen2.generate()

        names1 = [c.full_name for c in data1.candidates]
        names2 = [c.full_name for c in data2.candidates]
        assert names1 != names2

    def test_idempotent_generation(self) -> None:
        """Повторная генерация с тем же генератором стабильна."""
        settings = SeedSettings(random_seed=1, candidates_per_tenant=20)
        gen = SeedGenerator(settings)
        data1 = gen.generate()
        data2 = gen.generate()
        # Второй вызов генерирует заново (RNG state другой), но количество то же
        assert len(data1.candidates) == len(data2.candidates)


# ──────────────────────────────────────────────────────────────
# Количество сущностей
# ──────────────────────────────────────────────────────────────


class TestCounts:
    def _generate_small(self) -> object:
        settings = SeedSettings(
            random_seed=42,
            tenant_count=3,
            candidates_per_tenant=100,
            vacancies_per_tenant=10,
        )
        return SeedGenerator(settings).generate()

    def test_tenant_count(self) -> None:
        data = self._generate_small()
        assert len(data.tenants) == 3  # type: ignore[attr-defined]

    def test_roles_per_tenant(self) -> None:
        data = self._generate_small()
        # 6 системных ролей × 3 тенанта = 18
        assert len(data.roles) == 18  # type: ignore[attr-defined]

    def test_users_per_tenant(self) -> None:
        data = self._generate_small()
        # По 1 пользователю на роль × 6 ролей × 3 тенанта = 18
        assert len(data.users) == 18  # type: ignore[attr-defined]

    def test_candidates_count(self) -> None:
        data = self._generate_small()
        # 100 × 3 = 300
        assert len(data.candidates) == 300  # type: ignore[attr-defined]

    def test_vacancies_count(self) -> None:
        data = self._generate_small()
        # 10 × 3 = 30
        assert len(data.vacancies) == 30  # type: ignore[attr-defined]

    def test_pipeline_stages_count(self) -> None:
        data = self._generate_small()
        # 8 стадий × 30 вакансий = 240
        assert len(data.pipeline_stages) == 240  # type: ignore[attr-defined]

    def test_applications_exist(self) -> None:
        data = self._generate_small()
        assert len(data.applications) > 0  # type: ignore[attr-defined]

    def test_total_records(self) -> None:
        data = self._generate_small()
        assert data.total_records > 0  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────
# Мульти-тенантность
# ──────────────────────────────────────────────────────────────


class TestMultiTenant:
    def test_tenants_have_different_slugs(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        slugs = [t.slug for t in data.tenants]
        assert len(slugs) == len(set(slugs))

    def test_tenants_have_valid_names(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for t in data.tenants:
            assert t.name
            assert len(t.name) > 0

    def test_candidates_belong_to_tenants(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        tenant_ids = {t.id for t in data.tenants}
        for c in data.candidates:
            assert c.tenant_id in tenant_ids

    def test_vacancies_belong_to_tenants(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        tenant_ids = {t.id for t in data.tenants}
        for v in data.vacancies:
            assert v.tenant_id in tenant_ids


# ──────────────────────────────────────────────────────────────
# Данные кандидатов
# ──────────────────────────────────────────────────────────────


class TestCandidateData:
    def test_full_name_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for c in data.candidates:
            assert c.full_name
            assert len(c.full_name.split()) >= 2

    def test_source_valid(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        valid_sources = {
            "direct", "referral", "job_board",
            "database", "agency", "linkedin",
        }
        for c in data.candidates:
            assert c.source in valid_sources

    def test_skills_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for c in data.candidates:
            assert len(c.skills) >= 3

    def test_headline_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for c in data.candidates:
            assert c.headline


# ──────────────────────────────────────────────────────────────
# Данные вакансий
# ──────────────────────────────────────────────────────────────


class TestVacancyData:
    def test_role_description_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for v in data.vacancies:
            assert v.role_description
            assert len(v.role_description) > 20

    def test_requirements_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for v in data.vacancies:
            assert len(v.requirements) >= 5

    def test_nice_to_have_not_empty(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for v in data.vacancies:
            assert len(v.nice_to_have) >= 2

    def test_seniority_valid(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        valid_seniorities = {"junior", "middle", "senior", "lead"}
        for v in data.vacancies:
            assert v.seniority in valid_seniorities

    def test_status_valid(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        valid_statuses = {"draft", "active", "paused"}
        for v in data.vacancies:
            assert v.status in valid_statuses


# ──────────────────────────────────────────────────────────────
# Целостность откликов
# ──────────────────────────────────────────────────────────────


class TestApplicationIntegrity:
    def test_applications_reference_valid_candidates(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=50)
        data = SeedGenerator(settings).generate()
        candidate_ids = {c.id for c in data.candidates}
        for app in data.applications:
            assert app.candidate_id in candidate_ids

    def test_applications_reference_valid_vacancies(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=50)
        data = SeedGenerator(settings).generate()
        vacancy_ids = {v.id for v in data.vacancies}
        for app in data.applications:
            assert app.vacancy_id in vacancy_ids

    def test_application_tenant_matches(self) -> None:
        """Тенант отклика = тенант кандидата = тенант вакансии."""
        settings = SeedSettings(random_seed=42, candidates_per_tenant=50)
        data = SeedGenerator(settings).generate()
        candidate_tenants = {c.id: c.tenant_id for c in data.candidates}
        vacancy_tenants = {v.id: v.tenant_id for v in data.vacancies}
        for app in data.applications:
            assert app.tenant_id == candidate_tenants[app.candidate_id]
            assert app.tenant_id == vacancy_tenants[app.vacancy_id]

    def test_stage_valid(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=50)
        data = SeedGenerator(settings).generate()
        valid_stages = {
            "new", "screening", "phone_interview", "technical_interview",
            "final_interview", "offer", "hired", "rejected",
        }
        for app in data.applications:
            assert app.stage in valid_stages


# ──────────────────────────────────────────────────────────────
# Роли и пользователи
# ──────────────────────────────────────────────────────────────


class TestRolesAndUsers:
    def test_six_system_roles_per_tenant(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for tenant in data.tenants:
            tenant_roles = [r for r in data.roles if r.tenant_id == tenant.id]
            assert len(tenant_roles) == 6

    def test_role_permissions_is_json(self) -> None:
        import json

        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for r in data.roles:
            perms = json.loads(r.permissions)
            assert isinstance(perms, list)

    def test_admin_role_has_wildcard(self) -> None:
        import json

        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        admin_roles = [r for r in data.roles if r.name == "admin"]
        assert len(admin_roles) > 0
        for r in admin_roles:
            perms = json.loads(r.permissions)
            assert "*:*" in perms

    def test_user_emails_valid_format(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for u in data.users:
            assert "@" in u.email
            assert ".example.com" in u.email

    def test_users_have_roles(self) -> None:
        settings = SeedSettings(random_seed=42, candidates_per_tenant=10)
        data = SeedGenerator(settings).generate()
        for u in data.users:
            assert u.role_name
            assert u.role_name in {
                "admin", "head_of_recruiting", "recruiter",
                "sourcer", "hiring_manager", "viewer",
            }


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────


class TestCLI:
    def test_parse_args_defaults(self) -> None:
        from ats.infra.seeds.cli import _parse_args

        args = _parse_args([])
        assert args.seed is None
        assert args.tenants is None
        assert args.candidates is None
        assert args.vacancies is None
        assert args.dry_run is False
        assert args.no_truncate is False

    def test_parse_args_custom(self) -> None:
        from ats.infra.seeds.cli import _parse_args

        args = _parse_args(["--seed", "123", "--candidates", "100", "--dry-run"])
        assert args.seed == 123
        assert args.candidates == 100
        assert args.dry_run is True

    def test_build_settings_from_args(self) -> None:
        from ats.infra.seeds.cli import _build_settings, _parse_args

        args = _parse_args(["--seed", "77", "--tenants", "2", "--candidates", "50"])
        settings = _build_settings(args)
        assert settings.random_seed == 77
        assert settings.tenant_count == 2
        assert settings.candidates_per_tenant == 50

    def test_cli_dry_run(self) -> None:
        """CLI --dry-run генерирует данные без записи в БД."""
        from ats.infra.seeds.cli import main

        exit_code = main(["--candidates", "10", "--dry-run"])
        assert exit_code == 0
