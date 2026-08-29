"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Header } from "@/components/header";
import { ScreeningCriteriaView } from "@/components/screening-criteria-view";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import {
  SENIORITY_LABELS,
  type CreateVacancyRequest,
  type Seniority,
  type VacancyResponse,
} from "@/lib/types";

type Step = "form" | "loading" | "result";

export default function NewVacancyPage() {
  const [step, setStep] = useState<Step>("form");
  const [result, setResult] = useState<VacancyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [seniority, setSeniority] = useState<Seniority>("middle");
  const [team, setTeam] = useState("");
  const [description, setDescription] = useState("");

  const mutation = useMutation({
    mutationFn: (data: CreateVacancyRequest) => api.createVacancy(data),
    onSuccess: (data) => {
      setResult(data);
      setStep("result");
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Неизвестная ошибка");
      setStep("form");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setStep("loading");
    mutation.mutate({ title, seniority, team, description });
  };

  const canSubmit =
    title.trim() && team.trim() && description.trim() && !mutation.isPending;

  return (
    <>
      <Header />
      <main id="main" className="mx-auto max-w-3xl px-4 py-8">
        <Stepper step={step} />

        {step === "form" && (
          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Описание роли</CardTitle>
              <p className="text-sm text-fg-muted">
                Опишите вакансию — ИИ сгенерирует критерии скрининга на основе
                этого описания.
              </p>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <Label htmlFor="title">Название позиции</Label>
                  <Input
                    id="title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Напр. Python-разработчик"
                    required
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="seniority">Грейд</Label>
                    <select
                      id="seniority"
                      value={seniority}
                      onChange={(e) =>
                        setSeniority(e.target.value as Seniority)
                      }
                      className="h-10 w-full rounded-lg border border-border-strong bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                    >
                      {(Object.keys(SENIORITY_LABELS) as Seniority[]).map(
                        (s) => (
                          <option key={s} value={s}>
                            {SENIORITY_LABELS[s]}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                  <div>
                    <Label htmlFor="team">Команда</Label>
                    <Input
                      id="team"
                      value={team}
                      onChange={(e) => setTeam(e.target.value)}
                      placeholder="Напр. Backend-платформа"
                      required
                    />
                  </div>
                </div>

                <div>
                  <Label htmlFor="description">
                    Описание роли (обязанности, требования, условия)
                  </Label>
                  <Textarea
                    id="description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Подробно опишите, чем будет заниматься кандидат, какие технологии использовать, какие задачи решать…"
                    rows={8}
                    required
                  />
                  <p className="mt-1 text-xs text-fg-subtle">
                    Чем подробнее описание — тем точнее ИИ-критерии.
                  </p>
                </div>

                {error && (
                  <div
                    role="alert"
                    className="rounded-lg bg-danger-50 p-3 text-sm text-danger-700"
                  >
                    {error}
                  </div>
                )}

                <Button
                  type="submit"
                  size="lg"
                  className="w-full"
                  disabled={!canSubmit}
                  loading={mutation.isPending}
                >
                  {mutation.isPending
                    ? "ИИ генерирует критерии…"
                    : "Создать вакансию и сгенерировать критерии"}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {step === "loading" && (
          <Card className="mt-6">
            <CardContent className="flex flex-col items-center gap-4 p-10">
              <Button loading size="lg" disabled>
                Обработка
              </Button>
              <p className="text-sm text-fg-muted">
                ИИ анализирует описание роли и формирует критерии скрининга…
              </p>
            </CardContent>
          </Card>
        )}

        {step === "result" && result && (
          <div className="mt-6 space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Вакансия создана</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-2 text-sm">
                  <dt className="text-fg-muted">Позиция</dt>
                  <dd className="font-medium">{result.title}</dd>
                  <dt className="text-fg-muted">Грейд</dt>
                  <dd className="font-medium">
                    {SENIORITY_LABELS[result.seniority as Seniority]}
                  </dd>
                  <dt className="text-fg-muted">Команда</dt>
                  <dd className="font-medium">{result.team}</dd>
                  <dt className="text-fg-muted">Статус</dt>
                  <dd className="font-medium">{result.status}</dd>
                </dl>
                <div className="mt-4 font-mono text-xs text-fg-subtle">
                  ID: {result.id}
                </div>
              </CardContent>
            </Card>

            {result.criteria ? (
              <ScreeningCriteriaView
                criteria={result.criteria}
                provenanceId={result.criteria_provenance_id}
              />
            ) : (
              <Card>
                <CardContent className="p-6">
                  <div
                    role="alert"
                    className="rounded-lg bg-warning-50 p-3 text-sm text-warning-700"
                  >
                    ИИ-критерии не сгенерированы: {result.criteria_error}
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="flex gap-3">
              <Button
                variant="secondary"
                onClick={() => {
                  setStep("form");
                  setResult(null);
                }}
              >
                Создать ещё одну
              </Button>
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function Stepper({ step }: { step: Step }) {
  const steps = [
    { id: "form", label: "Описание роли" },
    { id: "loading", label: "Генерация ИИ" },
    { id: "result", label: "Критерии" },
  ];
  const activeIndex = steps.findIndex((s) => s.id === step);

  return (
    <ol className="flex items-center gap-2">
      {steps.map((s, i) => (
        <li key={s.id} className="flex items-center gap-2">
          <span
            className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
              i <= activeIndex
                ? "bg-brand-600 text-white"
                : "bg-bg-muted text-fg-subtle"
            }`}
            aria-current={i === activeIndex ? "step" : undefined}
          >
            {i + 1}
          </span>
          <span
            className={`text-sm ${
              i <= activeIndex ? "font-medium text-fg" : "text-fg-subtle"
            }`}
          >
            {s.label}
          </span>
          {i < steps.length - 1 && (
            <span className="mx-1 h-px w-8 bg-border" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}
