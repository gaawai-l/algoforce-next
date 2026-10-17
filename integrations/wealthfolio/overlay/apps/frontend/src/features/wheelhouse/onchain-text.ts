import { messages, type MessageKey, type TextFn } from "./i18n";
import type { LevelsView } from "./onchain-contract";

// Text helpers shared by the on-chain views.

type LineName = LevelsView["lines"][number]["name"];

export const lineNameKey: Record<LineName, MessageKey> = {
  true_mean: "levels.line.true_mean",
  short_term: "levels.line.short_term",
  average: "levels.line.average",
  long_term: "levels.line.long_term",
  median: "levels.line.median",
};

// "lin200" names the $200 bucket.
const aggBucket = (agg: string) => agg.replace(/^lin/, "$");

// Reason codes from the service; anything unknown is shown as received.
export function reasonText(text: TextFn, reason: string) {
  const series = /^series_missing:(.+)$/.exec(reason);
  if (series) return text("cycle.reason.seriesMissing", { name: series[1] });
  const snapshot = /^urpd_missing:([^:]+):([^:]+)$/.exec(reason);
  // "all" is the whole supply and reads as a phrase of its own; the cohorts keep their short names.
  if (snapshot)
    return snapshot[1] === "all"
      ? text("cycle.reason.urpdMissingAll", { bucket: aggBucket(snapshot[2]) })
      : text("cycle.reason.urpdMissingSnapshot", {
          cohort: snapshot[1].toUpperCase(),
          bucket: aggBucket(snapshot[2]),
        });
  const partial = /^urpd_grid_partial:([^:]+)$/.exec(reason);
  if (partial)
    return text("cycle.reason.urpdGridPartial", {
      bucket: aggBucket(partial[1]),
    });
  const empty = /^urpd_empty:([^:]+)$/.exec(reason);
  if (empty)
    return text("cycle.reason.urpdEmpty", { bucket: aggBucket(empty[1]) });
  const key = `cycle.reason.${reason}`;
  return Object.prototype.hasOwnProperty.call(messages.en, key)
    ? text(key as MessageKey)
    : reason;
}

type RuleCode = LevelsView["rules"][number];

const ruleKey: Record<RuleCode, MessageKey> = {
  O1: "rules.O1",
  O2: "rules.O2",
  O3: "rules.O3",
  O4: "rules.O4",
  O5: "rules.O5",
  O6: "rules.O6",
};

// The lines that say which rules produced a view: the codes with their short names, or "original
// v1" when none applied, then a note while the stored numbers are being recomputed.
export function rulesNote(
  text: TextFn,
  view: { rules: RuleCode[]; rules_pending: boolean },
) {
  const lines = [
    view.rules.length
      ? text("rules.line", {
          list: view.rules
            .map((code) => `${code} ${text(ruleKey[code])}`)
            .join(" · "),
        })
      : text("rules.original"),
  ];
  if (view.rules_pending) lines.push(text("rules.pending"));
  return lines;
}

// The rules lines of several views, each line naming its views: views whose lines read the same
// share them, so one line names them all, and a view that differs, or is the only one, is named.
export function rulesByView(
  text: TextFn,
  views: { title: string; view: Parameters<typeof rulesNote>[1] }[],
) {
  const groups: { titles: string[]; lines: string[] }[] = [];
  for (const { title, view } of views) {
    const lines = rulesNote(text, view);
    const same = groups.find(
      (group) => group.lines.join("\n") === lines.join("\n"),
    );
    if (same) same.titles.push(title);
    else groups.push({ titles: [title], lines });
  }
  return groups.flatMap(({ titles, lines }) =>
    lines.map((line) =>
      text("rules.forView", {
        view: titles.join(text("rules.viewSeparator")),
        line,
      }),
    ),
  );
}

// The cost-line timestamps are UTC instants; the day they name is the UTC day.
export const utcDay = (instant: string) =>
  new Date(instant).toISOString().slice(0, 10);
