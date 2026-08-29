"use client";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CANDIDATE_SOURCE_LABELS, type Facet } from "@/lib/types";

const FACET_TITLES: Record<string, string> = {
  skills: "Навыки",
  source: "Источник",
};

interface FacetPanelProps {
  facets: Facet[];
  selected: Record<string, string[]>;
  onToggle: (field: string, value: string) => void;
}

/**
 * Панель фасетной фильтрации.
 * USERFRIENDLY: чекбоксы с количеством, прокручиваемые списки.
 * БЫСТРЕЙШИЙ ПОИСК: быстрая фильтрация без перезагрузки страницы.
 */
export function FacetPanel({ facets, selected, onToggle }: FacetPanelProps) {
  if (facets.length === 0) return null;

  return (
    <div className="space-y-4">
      {facets.map((facet) => {
        const title = FACET_TITLES[facet.field] ?? facet.field;
        const checked = selected[facet.field] ?? [];

        return (
          <Card key={facet.field}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{title}</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="max-h-64 space-y-2 overflow-y-auto">
                {facet.values.map((fv) => {
                  const label =
                    facet.field === "source"
                      ? CANDIDATE_SOURCE_LABELS[
                          fv.value as keyof typeof CANDIDATE_SOURCE_LABELS
                        ] ?? fv.value
                      : fv.value;
                  return (
                    <Checkbox
                      key={fv.value}
                      id={`facet-${facet.field}-${fv.value}`}
                      checked={checked.includes(fv.value)}
                      onChange={() => onToggle(facet.field, fv.value)}
                      label={
                        <span className="flex w-full items-center justify-between">
                          <span className="truncate">{label}</span>
                          <Badge
                            tone="neutral"
                            className="ml-2 shrink-0"
                          >
                            {fv.count}
                          </Badge>
                        </span>
                      }
                    />
                  );
                })}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
