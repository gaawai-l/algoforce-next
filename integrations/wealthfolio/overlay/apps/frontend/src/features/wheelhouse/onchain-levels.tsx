import { useState, type ReactNode } from "react";
import { usd } from "./client";
import {
  useWheelhouseText,
  type MessageKey,
  type TextFn,
  type WheelhouseLocale,
} from "./i18n";
import type { CostBasisView, CycleView, LevelsView } from "./onchain-contract";
import { CostBasisPanel, type CostBucket } from "./cost-basis-panel";
import { lineNameKey, reasonText, rulesByView, utcDay } from "./onchain-text";

type LineName = LevelsView["lines"][number]["name"];
type ComponentName = CycleView["components"][number]["name"];
type CycleState = NonNullable<CycleView["state"]>;

const componentKey: Record<ComponentName, MessageKey> = {
  depth: "cycle.component.depth",
  spread: "cycle.component.spread",
  pvs: "cycle.component.pvs",
};
const stateKey: Record<CycleState, MessageKey> = {
  advance: "cycle.state.advance",
  breakout: "cycle.state.breakout",
  pressure: "cycle.state.pressure",
  repair: "cycle.state.repair",
  breakdown: "cycle.state.breakdown",
  capitulation: "cycle.state.capitulation",
};

const signed = (value: number) => {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded < 0 ? "−" : "+"}${Math.abs(rounded).toFixed(2)}`;
};

const dayPattern = /^(\d{4})-(\d{2})-(\d{2})$/;
// A UTC calendar day as "15 Oct" / "10月15日". It is formatted in UTC so it never shifts.
export function shortDay(text: TextFn, locale: WheelhouseLocale, day: string) {
  const [, year, month, date] = dayPattern.exec(day) ?? [];
  if (!year) return day;
  return text("cycle.date", {
    day: Number(date),
    month: new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
      month: locale === "zh" ? "numeric" : "short",
      timeZone: "UTC",
    }).format(Date.UTC(Number(year), Number(month) - 1, Number(date))),
  });
}

// The URPD snapshot day when it is older than the day the series are as of; the median is the
// only line built from URPD, so this is the day that median is really from.
export function olderUrpdDate(levels: LevelsView) {
  if (!levels.urpd_date || !levels.as_of) return null;
  return levels.urpd_date < utcDay(levels.as_of) ? levels.urpd_date : null;
}

// A line's name; the median carries its URPD date when that is older than the as-of day, so it
// never looks current.
export function lineLabel(
  text: TextFn,
  locale: WheelhouseLocale,
  levels: LevelsView,
  name: LineName,
) {
  const urpd = name === "median" ? olderUrpdDate(levels) : null;
  return urpd
    ? text("levels.line.medianUrpd", { date: shortDay(text, locale, urpd) })
    : text(lineNameKey[name]);
}

function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="wh-facts">
      {rows.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function OnchainLevels({
  levels,
  cycle,
  levelsError,
  cycleError,
  costBasis,
  costBasisError,
  bucket = 500,
}: {
  levels?: LevelsView;
  cycle?: CycleView;
  // A failed request wins over older data, so a failure never looks like a current reading.
  levelsError?: string;
  cycleError?: string;
  costBasis?: CostBasisView;
  costBasisError?: string;
  bucket?: CostBucket;
}) {
  const { locale, text } = useWheelhouseText();
  const missing = text("missing");
  // Read once: the sections start open on wide screens and collapsed on phones.
  const [wide] = useState(
    () =>
      typeof window.matchMedia !== "function" ||
      window.matchMedia("(min-width: 601px)").matches,
  );
  const lv = levelsError ? undefined : levels;
  const cy = cycleError ? undefined : cycle;
  const reasons = (view: { reasons: string[] }) =>
    view.reasons.length ? (
      <p className="wh-muted">
        {view.reasons.map((reason) => reasonText(text, reason)).join(" · ")}
      </p>
    ) : null;
  const unavailable = (title: string, error?: string, extra?: ReactNode) => (
    <>
      <p className="wh-onchain-warn">{title}</p>
      {error ? <p className="wh-muted">{error}</p> : null}
      {extra}
    </>
  );

  let linesBody: ReactNode;
  if (levelsError)
    linesBody = unavailable(text("levels.unavailable"), levelsError);
  else if (!lv)
    linesBody = <p className="wh-muted">{text("levels.loading")}</p>;
  else if (lv.data_state === "unavailable" || !lv.lines.length)
    linesBody = unavailable(text("levels.unavailable"), undefined, reasons(lv));
  else
    linesBody = (
      <>
        {lv.data_state === "stale" ? (
          <p className="wh-onchain-warn">
            {text("cycle.stale", {
              date: lv.as_of ? utcDay(lv.as_of) : missing,
            })}
          </p>
        ) : null}
        <Rows
          rows={lv.lines.map((line) => [
            lineLabel(text, locale, lv, line.name),
            usd(line.price),
          ])}
        />
        {reasons(lv)}
      </>
    );

  let cycleBody: ReactNode;
  if (cycleError)
    cycleBody = unavailable(text("cycle.unavailable"), cycleError);
  else if (!cy) cycleBody = <p className="wh-muted">{text("cycle.loading")}</p>;
  else if (
    cy.data_state === "unavailable" ||
    !cy.state ||
    cy.day == null ||
    !cy.as_of
  )
    cycleBody = unavailable(text("cycle.unavailable"), undefined, reasons(cy));
  else
    cycleBody = (
      <>
        {cy.data_state === "stale" ? (
          <p className="wh-onchain-warn">
            {text("cycle.stale", { date: cy.as_of })}
          </p>
        ) : null}
        <Rows
          rows={[
            [text("cycle.stateLabel"), text(stateKey[cy.state])],
            [
              text("cycle.sinceLabel"),
              text("cycle.dayCount", {
                date: cy.since ?? missing,
                day: cy.day,
              }),
            ],
            ...cy.components.map((component): [string, string] => [
              text(componentKey[component.name]),
              text("cycle.componentValue", {
                value: signed(component.value),
                deadband: component.deadband.toFixed(2),
                support: text(
                  component.supports ? "cycle.supports" : "cycle.opposes",
                ),
              }),
            ]),
          ]}
        />
        <p className="wh-muted">{text("cycle.componentsNote")}</p>
        {reasons(cy)}
      </>
    );

  const version = lv?.brk_version ?? cy?.brk_version ?? missing;
  const asOf = lv?.as_of
    ? lv.rules.includes("O1")
      ? // Under O1 the lines are those of the last closed day, never of the open one.
        text("levels.closedDate", { date: utcDay(lv.as_of) })
      : `${utcDay(lv.as_of)} UTC`
    : cy?.as_of
      ? cy.rules.includes("O1")
        ? text("levels.closedDate", { date: cy.as_of })
        : `${cy.as_of} UTC`
      : missing;
  // The reading includes the open day only while it is current; stale data has no open row.
  const forming =
    (lv?.data_state === "fresh" && lv.forming_at) ||
    (cy?.data_state === "fresh" && cy.forming_at);

  // The rules of each view, named; views with the same rules share a line. A view with no data was
  // derived under no rules, so it says nothing.
  const ruled: Parameters<typeof rulesByView>[1] = [];
  const addRules = (
    title: string,
    view?: Pick<LevelsView, "data_state" | "rules" | "rules_pending">,
  ) => {
    if (view && view.data_state !== "unavailable") ruled.push({ title, view });
  };
  addRules(
    text("costBasis.levelsTitle"),
    costBasisError ? undefined : costBasis,
  );
  addRules(text("levels.linesTitle"), lv);
  addRules(text("cycle.title"), cy);
  const rulesLines = rulesByView(text, ruled);

  return (
    <div className="wh-onchain">
      <CostBasisPanel view={costBasis} error={costBasisError} bucket={bucket} />
      <h3>{text("levels.linesTitle")}</h3>
      {linesBody}
      {lv?.refreshing || cy?.refreshing ? (
        <p role="status">{text("levels.refreshing")}</p>
      ) : null}
      <details
        id="wh-onchain-cycle"
        className="wh-onchain-cycle"
        tabIndex={-1}
        open={wide}
      >
        <summary>{text("cycle.title")}</summary>
        {cycleBody}
      </details>
      <details className="wh-onchain-source" open={wide}>
        <summary>{text("levels.source")}</summary>
        {lv || cy ? (
          <p>{text("levels.sourceLine", { version, date: asOf })}</p>
        ) : null}
        {lv ? (
          <p>
            {text("levels.urpdLine", {
              date: lv.urpd_date ? `${lv.urpd_date} UTC` : missing,
            })}
          </p>
        ) : null}
        {forming ? <p className="wh-muted">{text("cycle.forming")}</p> : null}
        {rulesLines.map((line) => (
          <p key={line} className="wh-muted">
            {line}
          </p>
        ))}
        <p className="wh-muted">{text("levels.sourceNote")}</p>
      </details>
    </div>
  );
}
