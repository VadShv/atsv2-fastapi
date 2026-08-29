import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-border bg-white">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold text-fg"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">
            A
          </span>
          ATS Core
        </Link>
        <nav className="flex items-center gap-1">
          <NavLink href="/vacancies/new">Новая вакансия</NavLink>
          <NavLink href="/search">Поиск кандидатов</NavLink>
        </nav>
      </div>
    </header>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-lg px-3 py-1.5 text-sm font-medium text-fg-muted transition-colors hover:bg-bg-muted hover:text-fg"
    >
      {children}
    </Link>
  );
}
