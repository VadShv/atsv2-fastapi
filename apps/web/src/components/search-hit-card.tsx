"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { SearchHit } from "@/lib/types";

interface SearchHitCardProps {
  hit: SearchHit;
  rank: number;
}

/**
 * Карточка результата поиска: ранк, headline, навыки, snippet, скор.
 * СКОРОСТЬ / БЫСТРЕЙШИЙ ПОИСК: скор виден сразу, разбивка bm25/vector.
 * WHITEBOX: прозрачная оценка релевантности.
 */
export function SearchHitCard({ hit, rank }: SearchHitCardProps) {
  const scorePct = Math.round(hit.score * 100);
  const bm25Pct = Math.round(hit.bm25_score * 100);
  const vectorPct = Math.round(hit.vector_score * 100);

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-bg-muted text-xs font-semibold text-fg-muted"
                aria-label={`Результат ${rank}`}
              >
                {rank}
              </span>
              <h3 className="truncate font-semibold text-fg">
                {hit.headline}
              </h3>
            </div>

            {hit.skills.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {hit.skills.slice(0, 12).map((skill) => (
                  <Badge key={skill} tone="brand">
                    {skill}
                  </Badge>
                ))}
                {hit.skills.length > 12 && (
                  <Badge tone="neutral">
                    +{hit.skills.length - 12}
                  </Badge>
                )}
              </div>
            )}

            {hit.snippet && (
              <p
                className="mt-2 text-sm text-fg-muted"
                dangerouslySetInnerHTML={{ __html: hit.snippet }}
              />
            )}

            <p
              className="mt-2 font-mono text-xs text-fg-subtle"
              title="Идентификатор документа"
            >
              {hit.document_id.slice(0, 8)}…
            </p>
          </div>

          {/* Скор релевантности */}
          <div className="shrink-0 text-right">
            <div className="text-2xl font-bold text-brand-700">
              {scorePct}%
            </div>
            <div className="mt-1 space-y-0.5 text-xs text-fg-subtle">
              <div>
                текст: <span className="font-medium text-fg-muted">{bm25Pct}%</span>
              </div>
              <div>
                семантика: <span className="font-medium text-fg-muted">{vectorPct}%</span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
