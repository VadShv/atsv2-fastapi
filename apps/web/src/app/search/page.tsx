"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Header } from "@/components/header";
import { FacetPanel } from "@/components/facet-panel";
import { SearchHitCard } from "@/components/search-hit-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { api, ApiError } from "@/lib/api";
import type { SearchFilter, SearchResponse } from "@/lib/types";

const PAGE_SIZE = 10;
const FACET_FIELDS = ["skills", "source"];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [skipEmbedding, setSkipEmbedding] = useState(false);
  const [offset, setOffset] = useState(0);
  const [facetsSelected, setFacetsSelected] = useState<
    Record<string, string[]>
  >({});
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: api.searchCandidates,
    onSuccess: (data) => {
      setResult(data);
      setError(null);
    },
    onError: (err: unknown) => {
      setError(err instanceof ApiError ? err.message : "Ошибка поиска");
      setResult(null);
    },
  });

  const buildFilters = (): SearchFilter[] =>
    Object.entries(facetsSelected)
      .filter(([, values]) => values.length > 0)
      .map(([field, values]) => ({
        field,
        values,
        operator: "any" as const,
      }));

  const doSearch = (newOffset: number) => {
    setOffset(newOffset);
    mutation.mutate({
      query: query.trim(),
      filters: buildFilters(),
      limit: PAGE_SIZE,
      offset: newOffset,
      facet_fields: FACET_FIELDS,
      skip_embedding: skipEmbedding || undefined,
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setOffset(0);
    doSearch(0);
  };

  const handleFacetToggle = (field: string, value: string) => {
    setFacetsSelected((prev) => {
      const current = prev[field] ?? [];
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value];
      return { ...prev, [field]: next };
    });
  };

  const hasActiveFacets = Object.values(facetsSelected).some(
    (v) => v.length > 0,
  );

  const clearFilters = () => {
    setFacetsSelected({});
    if (result && query.trim()) {
      doSearch(0);
    }
  };

  return (
    <>
      <Header />
      <main id="main" className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-bold text-fg">Поиск кандидатов</h1>
        <p className="mt-1 text-fg-muted">
          Гибридный поиск: текстовое соответствие + семантическая близость.
          Фильтруйте по навыкам и источнику.
        </p>

        {/* Поисковая строка */}
        <form onSubmit={handleSubmit} className="mt-6">
          <div className="flex gap-3">
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Напр. Python, FastAPI, PostgreSQL…"
              className="flex-1"
              aria-label="Поисковый запрос"
            />
            <Button
              type="submit"
              size="lg"
              loading={mutation.isPending}
              disabled={!query.trim()}
            >
              Искать
            </Button>
          </div>
          <div className="mt-3 flex items-center gap-4">
            <Checkbox
              id="skip-embedding"
              checked={skipEmbedding}
              onChange={(e) => setSkipEmbedding(e.target.checked)}
              label={
                <span className="text-fg-muted">
                  Только текстовый поиск (без семантики)
                </span>
              }
            />
          </div>
        </form>

        {/* Ошибка */}
        {error && (
          <div
            role="alert"
            className="mt-4 rounded-lg bg-danger-50 p-3 text-sm text-danger-700"
          >
            {error}
          </div>
        )}

        {/* Результаты */}
        {result && (
          <div className="mt-6">
            {/* Статус-бар */}
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-fg-muted">
                <span>
                  Найдено: <strong className="text-fg">{result.total}</strong>
                </span>
                <span className="text-fg-subtle">·</span>
                <span>{result.took_ms} мс</span>
                {skipEmbedding && <Badge tone="neutral">текст</Badge>}
              </div>
              {hasActiveFacets && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearFilters}
                >
                  Сбросить фильтры
                </Button>
              )}
            </div>

            <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
              {/* Фасеты */}
              <aside aria-label="Фильтры">
                <FacetPanel
                  facets={result.facets}
                  selected={facetsSelected}
                  onToggle={handleFacetToggle}
                />
              </aside>

              {/* Список хитов */}
              <div className="space-y-3">
                {result.hits.length === 0 ? (
                  <Card>
                    <CardContent className="p-10 text-center text-fg-muted">
                      Ничего не найдено. Попробуйте изменить запрос.
                    </CardContent>
                  </Card>
                ) : (
                  result.hits.map((hit, i) => (
                    <SearchHitCard
                      key={hit.document_id}
                      hit={hit}
                      rank={offset + i + 1}
                    />
                  ))
                )}

                {/* Пагинация */}
                {result.total > PAGE_SIZE && (
                  <div className="flex items-center justify-between pt-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => doSearch(offset - PAGE_SIZE)}
                      disabled={offset === 0 || mutation.isPending}
                    >
                      ← Назад
                    </Button>
                    <span className="text-sm text-fg-muted">
                      {offset + 1}–{Math.min(offset + PAGE_SIZE, result.total)} из {result.total}
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => doSearch(offset + PAGE_SIZE)}
                      disabled={
                        offset + PAGE_SIZE >= result.total ||
                        mutation.isPending
                      }
                    >
                      Вперёд →
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Пустое состояние */}
        {!result && !error && !mutation.isPending && (
          <Card className="mt-6">
            <CardContent className="p-10 text-center text-fg-muted">
              Введите запрос для поиска кандидатов в базе резюме.
            </CardContent>
          </Card>
        )}
      </main>
    </>
  );
}
