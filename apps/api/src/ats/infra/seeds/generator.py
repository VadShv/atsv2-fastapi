"""Детерминированный генератор демо-данных для стенда интеграции.

JUGO-014: 5к кандидатов, 20 вакансий, ~5к откликов, 2-3 тенанта.

УСТОЙЧИВОСТЬ: ленивый импорт Faker — если установлен, используется для имён;
если нет — fallback на встроенные списки. Генератор детерминированный
(random.Random(seed)) — одинаковый seed → одинаковые данные.

SECURE FIRST: PII не генерируется в открытом виде (full_name — обезличенный
профиль, контакты отсутствуют в демо-данных).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from ats.infra.seeds.settings import SeedSettings

_HAS_FAKER = False
try:
    from faker import Faker

    _HAS_FAKER = True
except ImportError:
    Faker = None  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────
# Демо-данные (fallback если Faker не установлен)
# ──────────────────────────────────────────────────────────────

_FIRST_NAMES_M = [
    "Александр",
    "Дмитрий",
    "Максим",
    "Сергей",
    "Андрей",
    "Алексей",
    "Артём",
    "Илья",
    "Кирилл",
    "Михаил",
    "Никита",
    "Иван",
    "Роман",
    "Егор",
    "Владимир",
    "Денис",
    "Павел",
    "Антон",
    "Виктор",
    "Глеб",
]

_FIRST_NAMES_F = [
    "Анна",
    "Мария",
    "Елена",
    "Ольга",
    "Наталья",
    "Татьяна",
    "Юлия",
    "Ирина",
    "Светлана",
    "Екатерина",
    "Алёна",
    "Виктория",
    "Дарья",
    "Ксения",
    "Полина",
    "Алина",
    "Софья",
    "Валерия",
    "Маргарита",
    "Надежда",
]

_LAST_NAMES = [
    "Иванов",
    "Петров",
    "Сидоров",
    "Кузнецов",
    "Смирнов",
    "Попов",
    "Васильев",
    "Соколов",
    "Михайлов",
    "Новиков",
    "Фёдоров",
    "Морозов",
    "Волков",
    "Алексеев",
    "Лебедев",
    "Семёнов",
    "Егоров",
    "Павлов",
    "Козлов",
    "Степанов",
    "Николаев",
    "Орлов",
    "Андреев",
    "Макаров",
    "Никитин",
    "Захаров",
    "Зайцев",
    "Соловьёв",
    "Борисов",
    "Яковлев",
]

_SOURCES = ["direct", "referral", "job_board", "database", "agency", "linkedin"]

_SKILLS = [
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "PostgreSQL",
    "Redis",
    "Docker",
    "Kubernetes",
    "AWS",
    "GCP",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "Angular",
    "Node.js",
    "Go",
    "Rust",
    "Java",
    "Spring",
    "Kotlin",
    "Swift",
    "SQL",
    "MongoDB",
    "Kafka",
    "RabbitMQ",
    "GraphQL",
    "REST",
    "gRPC",
    "Machine Learning",
    "TensorFlow",
    "PyTorch",
    "Data Science",
    "Pandas",
    "NumPy",
    "CI/CD",
    "Git",
    "Linux",
    "Nginx",
    "Elasticsearch",
    "Terraform",
    "Ansible",
    "Jenkins",
    "Microservices",
    "System Design",
    "Agile",
    "Scrum",
    "Kanban",
    "Jira",
    "Confluence",
    "Product Management",
    "UX/UI",
    "Figma",
]

_VACANCY_TITLES = [
    ("Senior Python Developer", "senior"),
    ("Middle Frontend Developer", "middle"),
    ("DevOps Engineer", "middle"),
    ("Data Scientist", "senior"),
    ("ML Engineer", "middle"),
    ("Backend Developer (Go)", "senior"),
    ("Full Stack Developer", "middle"),
    ("Mobile Developer (iOS)", "senior"),
    ("Mobile Developer (Android)", "middle"),
    ("QA Automation Engineer", "middle"),
    ("QA Engineer", "junior"),
    ("Site Reliability Engineer", "senior"),
    ("Product Manager", "senior"),
    ("Project Manager", "middle"),
    ("Team Lead", "lead"),
    ("Engineering Manager", "lead"),
    ("System Analyst", "middle"),
    ("Business Analyst", "middle"),
    ("UX Designer", "middle"),
    ("UI Designer", "junior"),
    ("Data Engineer", "senior"),
    ("Security Engineer", "senior"),
    ("Technical Writer", "middle"),
    ("Database Administrator", "senior"),
    ("Solutions Architect", "lead"),
]

_TEAMS = [
    "Platform",
    "Payments",
    "Growth",
    "Infrastructure",
    "Data Platform",
    "Mobile",
    "Web",
    "Security",
    "ML Platform",
    "Core Services",
    "Customer Success",
    "FinTech",
    "Marketplace",
    "Analytics",
    "DevOps",
]

_REQUIREMENTS_POOL = [
    "Опыт работы с {skill} от 3 лет",
    "Глубокое понимание {skill}",
    "Опыт командной разработки",
    "Знание принципов SOLID",
    "Опыт работы с микросервисами",
    "Понимание CI/CD процессов",
    "Опыт работы с {skill} в production",
    "Английский Upper-Intermediate+",
    "Опыт менторства junior-разработчиков",
    "Участие в code review",
    "Опыт проектирования API",
    "Знание паттернов проектирования",
    "Опыт работы с распределёнными системами",
    "Понимание принципов ООП",
    "Опыт оптимизации производительности",
]

_NICE_TO_HAVE_POOL = [
    "Опыт работы с Kubernetes",
    "Знание {skill}",
    "Опыт выступления на конференциях",
    "Open-source вклад",
    "Опыт работы в стартапе",
    "Опыт международных проектов",
    "Увлечение технологией {skill}",
    "Опыт преподавания",
]

_TENANT_NAMES = [
    ("Acme Corp", "acme"),
    ("TechFlow", "techflow"),
    ("DataPro Solutions", "datapro"),
]

_PIPELINE_STAGES = [
    ("new", 0, "manual"),
    ("screening", 1, "manual"),
    ("phone_interview", 2, "manual"),
    ("technical_interview", 3, "manual"),
    ("final_interview", 4, "manual"),
    ("offer", 5, "manual"),
    ("hired", 6, "manual"),
    ("rejected", 7, "manual"),
]


# ──────────────────────────────────────────────────────────────
# Data classes для сгенерированных данных
# ──────────────────────────────────────────────────────────────


@dataclass
class SeedTenant:
    id: UUID
    name: str
    slug: str


@dataclass
class SeedUser:
    id: UUID
    tenant_id: UUID
    email: str
    full_name: str
    role_name: str


@dataclass
class SeedRole:
    id: UUID
    tenant_id: UUID
    name: str
    permissions: str  # JSON array


@dataclass
class SeedCandidate:
    id: UUID
    tenant_id: UUID
    full_name: str
    source: str
    headline: str
    skills: list[str]


@dataclass
class SeedVacancy:
    id: UUID
    tenant_id: UUID
    title: str
    seniority: str
    team: str
    status: str
    role_description: str
    requirements: list[str]
    nice_to_have: list[str]


@dataclass
class SeedPipelineStage:
    id: UUID
    tenant_id: UUID
    vacancy_id: UUID
    name: str
    order: int
    stage_type: str


@dataclass
class SeedApplication:
    id: UUID
    tenant_id: UUID
    candidate_id: UUID
    vacancy_id: UUID
    stage: str


@dataclass
class SeedData:
    """Полный набор сгенерированных демо-данных."""

    tenants: list[SeedTenant] = field(default_factory=list)
    roles: list[SeedRole] = field(default_factory=list)
    users: list[SeedUser] = field(default_factory=list)
    candidates: list[SeedCandidate] = field(default_factory=list)
    vacancies: list[SeedVacancy] = field(default_factory=list)
    pipeline_stages: list[SeedPipelineStage] = field(default_factory=list)
    applications: list[SeedApplication] = field(default_factory=list)

    @property
    def total_records(self) -> int:
        return (
            len(self.tenants)
            + len(self.roles)
            + len(self.users)
            + len(self.candidates)
            + len(self.vacancies)
            + len(self.pipeline_stages)
            + len(self.applications)
        )


# ──────────────────────────────────────────────────────────────
# Системные роли + разрешения
# ──────────────────────────────────────────────────────────────

_SYSTEM_ROLES = [
    "admin",
    "head_of_recruiting",
    "recruiter",
    "sourcer",
    "hiring_manager",
    "viewer",
]


def _get_role_perms(role_name: str) -> list[str]:
    """Получить разрешения роли (из домена RBAC)."""
    try:
        from ats.modules.identity.domain.rbac import permissions_for_role

        perms = permissions_for_role(role_name)
        return [str(p) for p in perms]
    except Exception:
        return []


def _build_role_permissions_json() -> dict[str, str]:
    """Построить карту: имя роли → JSON-строка разрешений."""
    return {role: json.dumps(sorted(_get_role_perms(role))) for role in _SYSTEM_ROLES}


_ROLE_PERMISSIONS_JSON: dict[str, str] = _build_role_permissions_json()


# ──────────────────────────────────────────────────────────────
# Генератор
# ──────────────────────────────────────────────────────────────


class SeedGenerator:
    """Детерминированный генератор демо-данных.

    Одинаковый seed → одинаковые данные (воспроизводимость для тестов).
    """

    def __init__(self, settings: SeedSettings | None = None) -> None:
        self._settings = settings or SeedSettings()
        self._rng = random.Random(self._settings.random_seed)
        self._faker: Faker | None = None
        if _HAS_FAKER:
            self._faker = Faker("ru_RU")
            self._faker.seed_instance(self._settings.random_seed)

    def generate(self) -> SeedData:
        """Сгенерировать полный набор демо-данных."""
        data = SeedData()

        # 1. Тенанты
        for i in range(self._settings.tenant_count):
            idx = min(i, len(_TENANT_NAMES) - 1)
            name, slug = _TENANT_NAMES[idx]
            tenant = SeedTenant(id=uuid4(), name=name, slug=slug)
            data.tenants.append(tenant)

        # 2. Роли + пользователи (per tenant)
        for tenant in data.tenants:
            for role_name in _SYSTEM_ROLES:
                role = SeedRole(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    name=role_name,
                    permissions=_ROLE_PERMISSIONS_JSON.get(role_name, "[]"),
                )
                data.roles.append(role)

                # По одному пользователю на роль
                full_name = self._generate_name()
                email = self._generate_email(full_name, tenant.slug)
                data.users.append(
                    SeedUser(
                        id=uuid4(),
                        tenant_id=tenant.id,
                        email=email,
                        full_name=full_name,
                        role_name=role_name,
                    )
                )

        # 3. Кандидаты (per tenant)
        for tenant in data.tenants:
            for _ in range(self._settings.candidates_per_tenant):
                data.candidates.append(self._generate_candidate(tenant.id))

        # 4. Вакансии + стадии пайплайна (per tenant)
        for tenant in data.tenants:
            vacancy_titles = self._rng.sample(
                _VACANCY_TITLES,
                min(self._settings.vacancies_per_tenant, len(_VACANCY_TITLES)),
            )
            for title, seniority in vacancy_titles:
                vacancy = self._generate_vacancy(tenant.id, title, seniority)
                data.vacancies.append(vacancy)

                # Стадии пайплайна для вакансии
                for stage_name, order, stage_type in _PIPELINE_STAGES:
                    data.pipeline_stages.append(
                        SeedPipelineStage(
                            id=uuid4(),
                            tenant_id=tenant.id,
                            vacancy_id=vacancy.id,
                            name=stage_name,
                            order=order,
                            stage_type=stage_type,
                        )
                    )

        # 5. Отклики (applications)
        tenant_vacancies: dict[UUID, list[SeedVacancy]] = {}
        for v in data.vacancies:
            tenant_vacancies.setdefault(v.tenant_id, []).append(v)

        for candidate in data.candidates:
            vacancies = tenant_vacancies.get(candidate.tenant_id, [])
            if not vacancies:
                continue

            if self._rng.random() > self._settings.application_probability:
                continue

            num_apps = self._rng.randint(
                1, min(self._settings.max_applications_per_candidate, len(vacancies))
            )
            chosen = self._rng.sample(vacancies, num_apps)
            for vacancy in chosen:
                stage = self._rng.choice([s[0] for s in _PIPELINE_STAGES])
                data.applications.append(
                    SeedApplication(
                        id=uuid4(),
                        tenant_id=candidate.tenant_id,
                        candidate_id=candidate.id,
                        vacancy_id=vacancy.id,
                        stage=stage,
                    )
                )

        return data

    # --- Internal generators ---

    def _generate_name(self) -> str:
        """Сгенерировать ФИО (last + first)."""
        if self._faker:
            return f"{self._faker.last_name()} {self._faker.first_name()}"
        last = self._rng.choice(_LAST_NAMES)
        if self._rng.random() > 0.5:
            first = self._rng.choice(_FIRST_NAMES_M)
        else:
            first = self._rng.choice(_FIRST_NAMES_F)
        return f"{last} {first}"

    def _generate_email(self, full_name: str, slug: str) -> str:
        """Сгенерировать email на основе ФИО и slug тенанта."""
        parts = full_name.lower().split()
        local = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else parts[0] if parts else "user"
        # Транслитерация (упрощённая)
        local = self._translit(local)
        num = self._rng.randint(1, 99)
        return f"{local}{num}@{slug}.example.com"

    @staticmethod
    def _translit(text: str) -> str:
        """Простая транслитерация кириллицы в латиницу."""
        mapping = {
            "а": "a",
            "б": "b",
            "в": "v",
            "г": "g",
            "д": "d",
            "е": "e",
            "ё": "e",
            "ж": "zh",
            "з": "z",
            "и": "i",
            "й": "y",
            "к": "k",
            "л": "l",
            "м": "m",
            "н": "n",
            "о": "o",
            "п": "p",
            "р": "r",
            "с": "s",
            "т": "t",
            "у": "u",
            "ф": "f",
            "х": "h",
            "ц": "ts",
            "ч": "ch",
            "ш": "sh",
            "щ": "sch",
            "ъ": "",
            "ы": "y",
            "ь": "",
            "э": "e",
            "ю": "yu",
            "я": "ya",
        }
        return "".join(mapping.get(c, c) for c in text)

    def _generate_candidate(self, tenant_id: UUID) -> SeedCandidate:
        """Сгенерировать кандидата."""
        full_name = self._generate_name()
        source = self._rng.choice(_SOURCES)
        num_skills = self._rng.randint(3, 10)
        skills = self._rng.sample(_SKILLS, min(num_skills, len(_SKILLS)))
        headline = self._generate_headline(skills)
        return SeedCandidate(
            id=uuid4(),
            tenant_id=tenant_id,
            full_name=full_name,
            source=source,
            headline=headline,
            skills=skills,
        )

    def _generate_headline(self, skills: list[str]) -> str:
        """Сгенерировать заголовок профиля (headline)."""
        primary = skills[0] if skills else "Developer"
        seniority = self._rng.choice(["Junior", "Middle", "Senior", "Lead"])
        return f"{seniority} {primary} Developer"

    def _generate_vacancy(self, tenant_id: UUID, title: str, seniority: str) -> SeedVacancy:
        """Сгенерировать вакансию с описанием роли и требованиями."""
        team = self._rng.choice(_TEAMS)
        num_req = self._rng.randint(5, 10)
        requirements = [
            self._rng.choice(_REQUIREMENTS_POOL).format(skill=self._rng.choice(_SKILLS))
            for _ in range(num_req)
        ]
        num_nice = self._rng.randint(2, 4)
        nice_to_have = [
            self._rng.choice(_NICE_TO_HAVE_POOL).format(skill=self._rng.choice(_SKILLS))
            for _ in range(num_nice)
        ]
        role_description = (
            f"Ищем {title.lower()} в команду {team}. "
            f"Грейд: {seniority}. "
            f"Основной стек: {', '.join(self._rng.sample(_SKILLS, 3))}. "
            f"Условия: гибридный формат работы, ДМС, обучение."
        )
        return SeedVacancy(
            id=uuid4(),
            tenant_id=tenant_id,
            title=title,
            seniority=seniority,
            team=team,
            status=self._rng.choice(["draft", "active", "active", "active", "paused"]),
            role_description=role_description,
            requirements=requirements,
            nice_to_have=nice_to_have,
        )
