import Link from "next/link";
import { Header } from "@/components/header";
import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";

export default function HomePage() {
  return (
    <>
      <Header />
      <main id="main" className="mx-auto max-w-6xl px-4 py-10">
        <h1 className="text-2xl font-bold text-fg">Рабочее пространство</h1>
        <p className="mt-1 text-fg-muted">
          AI-native система подбора персонала. Начните с создания вакансии или
          поиска кандидатов.
        </p>

        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          <Link href="/vacancies/new" className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <CardContent className="flex h-full flex-col gap-2 p-6">
                <CardTitle>Создать вакансию</CardTitle>
                <CardDescription>
                  Опишите роль — ИИ автоматически сгенерирует критерии
                  скрининга для оценки кандидатов.
                </CardDescription>
                <span className="mt-auto text-sm font-medium text-brand-700">
                  Начать →
                </span>
              </CardContent>
            </Card>
          </Link>

          <Link href="/search" className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <CardContent className="flex h-full flex-col gap-2 p-6">
                <CardTitle>Поиск кандидатов</CardTitle>
                <CardDescription>
                  Гибридный поиск по базе резюме: текст + семантика + фильтры
                  по навыкам.
                </CardDescription>
                <span className="mt-auto text-sm font-medium text-brand-700">
                  Искать →
                </span>
              </CardContent>
            </Card>
          </Link>
        </div>
      </main>
    </>
  );
}
