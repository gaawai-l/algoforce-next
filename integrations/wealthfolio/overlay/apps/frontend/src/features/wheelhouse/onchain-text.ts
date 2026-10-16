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

// The cost-line timestamps are UTC instants; the day they name is the UTC day.
export const utcDay = (instant: string) =>
  new Date(instant).toISOString().slice(0, 10);
