"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  CATEGORY_LABELS,
  type Criterion,
  type ScreeningCriteriaOutput,
} from "@/lib/types";
import { cn } from "@/lib/utils";

interface ScreeningCriteriaViewProps {
  criteria: ScreeningCriteriaOutput;
  provenanceId: string | null;
}

/**
 * Отображение AI-сгенерированных критериев скрининга с inline accept/reject.
 * USERFRIENDLY: progressive disclosure, быстрые действия.
 * WHITEBOX: provenance-ссылка, reasoning, scoring logic видны.
 */
export function ScreeningCriteriaView({
  criteria,
  provenanceId,
}: ScreeningCriteriaViewProps) {
  const allCriteria = criteria.groups.flatMap((g) => g.criteria);
  const [decisions, setDecisions] = useState<Record<string, "accepted" | "rejected" | undefined>>(
    () => Object.fromEntries(allCriteria.map((c) => [c.name, "accepted" as const])),
  );

  const acceptedCount = Object.values(decisions).filter(
    (d) => d === "accepted",
  ).length;
  const rejectedCount = Object.values(decisions).filter(
    (d) => d === "rejected",
  ).length;

  const setDecision = (name: string, decision: "accepted" | "rejected") => {
    setDecisions((prev) => ({ ...prev, [name]: decision }));
  };

  return (
    <div className="space-y-4">
      {/* Сводка ИИ */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>ИИ-критерии скрининга</CardTitle>
            <Badge tone="brand">Сгенерировано ИИ</Badge>
          </div>
          <CardDescription>{criteria.summary}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-lg bg-bg-subtle p-3 text-sm text-fg-muted">
            <p className="font-medium text-fg">Логика скоринга</p>
            <p className="mt-1">{criteria.scoring_logic}</p>
          </div>
          {criteria.reasoning && (
            <details className="group">
              <summary className="cursor-pointer text-sm font-medium text-brand-700">
                Обоснование ИИ (reasoning)
              </summary>
              <p className="mt-2 rounded-lg bg-bg-subtle p-3 text-sm text-fg-muted">
                {criteria.reasoning}
              </p>
            </details>
          )}
          {provenanceId && (
            <p className="font-mono text-xs text-fg-subtle" title="Provenance ID">
              provenance: {provenanceId.slice(0, 8)}…
            </p>
          )}
          <div className="flex gap-3 text-sm">
            <span className="text-success-700">Принято: {acceptedCount}</span>
            <span className="text-danger-700">Отклонено: {rejectedCount}</span>
            <span className="text-fg-subtle">
              Всего: {allCriteria.length}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Группы критериев */}
      {criteria.groups.map((group) => (
        <Card key={group.category}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {CATEGORY_LABELS[group.category]}
              </CardTitle>
              <Badge tone={group.category === "red_flag" ? "warning" : "neutral"}>
                вес {group.weight}%
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {group.criteria.map((criterion) => (
              <CriterionRow
                key={criterion.name}
                criterion={criterion}
                decision={decisions[criterion.name]}
                onAccept={() => setDecision(criterion.name, "accepted")}
                onReject={() => setDecision(criterion.name, "rejected")}
              />
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function CriterionRow({
  criterion,
  decision,
  onAccept,
  onReject,
}: {
  criterion: Criterion;
  decision: "accepted" | "rejected" | undefined;
  onAccept: () => void;
  onReject: () => void;
}) {
  const accepted = decision === "accepted";

  return (
    <div
      className={cn(
        "flex items-start justify-between gap-3 rounded-lg border p-3 transition-colors",
        decision === "rejected"
          ? "border-danger-200 bg-danger-50/50 opacity-60"
          : "border-border bg-white",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-fg">{criterion.name}</span>
          {criterion.must_have && (
            <Badge tone="danger">обязательно</Badge>
          )}
          <Badge tone="neutral">{criterion.weight}%</Badge>
        </div>
        <p className="mt-1 text-sm text-fg-muted">{criterion.description}</p>
        <p className="mt-1 text-xs text-fg-subtle">
          Проверка: {criterion.verification}
        </p>
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="sm"
          variant={accepted ? "success" : "ghost"}
          onClick={onAccept}
          aria-pressed={accepted}
          aria-label={`Принять критерий: ${criterion.name}`}
        >
          ✓
        </Button>
        <Button
          size="sm"
          variant={!accepted ? "danger" : "ghost"}
          onClick={onReject}
          aria-pressed={!accepted}
          aria-label={`Отклонить критерий: ${criterion.name}`}
        >
          ✕
        </Button>
      </div>
    </div>
  );
}
