import { useState, type ReactNode } from "react";
import { usd } from "./client";
import {
  messages,
  useWheelhouseText,
  type MessageKey,
  type TextFn,
} from "./i18n";
import type { CycleView, LevelsView } from "./onchain-contract";

type LineName = LevelsView["lines"][number]["name"];
type ComponentName = CycleView["components"][number]["name"];
type CycleState = NonNullable<CycleView["state"]>;

export const lineNameKey: Record<LineName, MessageKey> = {
  true_mean: "levels.line.true_mean",
  short_term: "levels.line.short_term",
  average: "levels.line.average",
  long_term: "levels.line.long_term",
  median: "levels.line.median",
};
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

// Reason codes from the service; anything unknown is shown as received.
function reasonText(text: TextFn, reason: string) {
  const series = /^series_missing:(.+)$/.exec(reason);
  if (series) return text("cycle.reason.seriesMissing", { name: series[1] });
  const key = `cycle.reason.${reason}`;
  return Object.prototype.hasOwnProperty.call(messages.en, key)
    ? text(key as MessageKey)
    : reason;
}

const signed = (value: number) => {
  const rounded = Math.round(value * 100) / 100;
  return `${rounded < 0 ? "−" : "+"}${Math.abs(rounded).toFixed(2)}`;
};
// The cost-line timestamps are UTC instants; the day they name is the UTC day.
const utcDay = (instant: string) =>
  new Date(instant).toISOString().slice(0, 10);

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
}: {
  levels?: LevelsView;
  cycle?: CycleView;
  // A failed request wins over older data, so a failure never looks like a current reading.
  levelsError?: string;
  cycleError?: string;
}) {
  const { text } = useWheelhouseText();
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
            text(lineNameKey[line.name]),
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
    ? `${utcDay(lv.as_of)} UTC`
    : cy?.as_of
      ? `${cy.as_of} UTC`
      : missing;
  // The reading includes the open day only while it is current; stale data has no open row.
  const forming =
    (lv?.data_state === "fresh" && lv.forming_at) ||
    (cy?.data_state === "fresh" && cy.forming_at);

  return (
    <div className="wh-onchain">
      <h3>{text("levels.linesTitle")}</h3>
      {linesBody}
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
        {forming ? <p className="wh-muted">{text("cycle.forming")}</p> : null}
        <p className="wh-muted">{text("levels.sourceNote")}</p>
        {lv?.refreshing || cy?.refreshing ? (
          <p role="status">{text("levels.refreshing")}</p>
        ) : null}
      </details>
    </div>
  );
}
