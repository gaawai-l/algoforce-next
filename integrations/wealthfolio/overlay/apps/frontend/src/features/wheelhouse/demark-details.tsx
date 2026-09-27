import { Dropdown, DropdownOption } from "./dropdown";
import { useState } from "react";
import type { DemarkResult, DemarkSequence } from "./demark-contract";
import { stamp } from "./client";
import { issueText, labeled, useWheelhouseText, type TextFn } from "./i18n";

export const exactPrice = (value: string | null | undefined, missing = "Unavailable") =>
  value ?? missing;

function sequenceLabel(s: DemarkSequence, text: TextFn) {
  const side = s.side === "buy" ? text("demark.buyMove") : text("demark.sellMove");
  const stage =
    s.countdown_status === "inactive"
      ? text("demark.setupProgress", { count: s.setup_count })
      : text("demark.countdownProgress", { count: s.countdown_count });
  const status =
    s.countdown_status === "inactive"
      ? labeled(text, "status", s.setup_status)
      : s.countdown_status === "qualified13"
        ? text("demark.qualifiedRisk", { risk: labeled(text, "status", s.risk_status) })
        : labeled(text, "status", s.countdown_status);
  return `${side} · ${stage} · ${status}`;
}

export function DemarkDetails({
  result,
  selectedId,
  onSelect,
}: {
  result: DemarkResult | null | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const when = (value: string | null | undefined) => stamp(value, missing);
  const price = (value: string | null | undefined) => exactPrice(value, missing);
  const [showHistory, setShowHistory] = useState(false);
  if (!result) return <p>{text("demark.missing")}</p>;
  const all = [...result.sequences].reverse();
  const current = all.filter(
    (s) =>
      s.continuity === "observed" &&
      (s.setup_status === "forming" ||
        ["active", "count13_unqualified"].includes(s.countdown_status) ||
        s.risk_status === "valid"),
  );
  const options = showHistory ? all : current;
  const selected =
    all.find((s) => s.sequence_id === selectedId) ?? current[0] ?? all[0];
  return (
    <>
      <span className="wh-badge">
        {text("demark.sequential")} · {labeled(text, "status", result.status).toUpperCase()}
      </span>
      <details className="wh-td-explainer">
        <summary>{text("demark.how")}</summary>
        <p>{text("demark.howBody")}</p>
      </details>
      <label className="wh-inline">
        <input
          type="checkbox"
          checked={showHistory}
          onChange={(e) => setShowHistory(e.target.checked)}
        />{" "}
        {text("demark.includeEnded")}
      </label>
      <label className="wh-td-picker">
        {text("demark.sequence")}
        <Dropdown
          aria-label={text("demark.aria")}
          value={selected?.sequence_id ?? ""}
          onValueChange={(value) => onSelect(value)}
        >
          {!selected && <DropdownOption value="">{text("demark.none")}</DropdownOption>}
          {selected && !options.includes(selected) && (
            <DropdownOption value={selected.sequence_id}>
              {sequenceLabel(selected, text)} · {text("demark.historical")}
            </DropdownOption>
          )}
          {options.map((s) => (
            <DropdownOption key={s.sequence_id} value={s.sequence_id}>
              {sequenceLabel(s, text)} · {when(s.setup_bars[0].close_time).slice(0, 16)}
            </DropdownOption>
          ))}
        </Dropdown>
      </label>
      {selected && (
        <>
          <h3>{selected.side === "buy" ? text("demark.buySeq") : text("demark.sellSeq")}</h3>
          <dl className="wh-facts">
            <div>
              <dt>{text("demark.setup")}</dt>
              <dd>
                {selected.setup_count}/9 · {labeled(text, "status", selected.setup_status)}
              </dd>
            </div>
            <div>
              <dt>{text("demark.perfection")}</dt>
              <dd>
                {selected.setup_perfected === null
                  ? text("demark.unknownPerfection")
                  : selected.setup_perfected
                    ? text("demark.perfected")
                    : result.config.perfection_policy === "strict_at_nine"
                      ? text("demark.notPerfected")
                      : text("demark.awaitingPerfection")}
              </dd>
            </div>
            <div>
              <dt>{text("demark.countdown")}</dt>
              <dd>
                {selected.countdown_count}/13 ·{" "}
                {selected.countdown_status === "count13_unqualified"
                  ? text("demark.deferred13")
                  : labeled(text, "status", selected.countdown_status)}
              </dd>
            </div>
            <div>
              <dt>{text("demark.continuity")}</dt>
              <dd>
                {selected.continuity === "lost" ? text("demark.gap") : text("demark.observed")}
              </dd>
            </div>
            <div>
              <dt>
                {selected.side === "buy" ? text("demark.tdstResistance") : text("demark.tdstSupport")}
              </dt>
              <dd>{price(selected.tdst)}</dd>
            </div>
            <div>
              <dt>{text("demark.countdown8")}</dt>
              <dd>{price(selected.qualification_threshold)}</dd>
            </div>
            <div>
              <dt>
                {text("demark.risk", { status: labeled(text, "status", selected.risk_status) })}
              </dt>
              <dd>
                {selected.risk_status === "valid"
                  ? price(selected.risk_level)
                  : text("demark.inactiveRisk")}
              </dd>
            </div>
            <div>
              <dt>{text("demark.qualifiedAt")}</dt>
              <dd>{when(selected.qualified_at)}</dd>
            </div>
            <div>
              <dt>{text("demark.confirmation")}</dt>
              <dd>{price(selected.confirmation_close)}</dd>
            </div>
            <div>
              <dt>{text("demark.sinceSetup")}</dt>
              <dd>
                {selected.bars_since_setup9 === null
                  ? "—"
                  : text("demark.bars", {
                      count: selected.bars_since_setup9,
                      seconds: selected.elapsed_since_setup9_seconds ?? "",
                    })}
              </dd>
            </div>
            <div>
              <dt>{text("demark.since13")}</dt>
              <dd>
                {selected.bars_since_qualified13 === null
                  ? "—"
                  : text("demark.bars", {
                      count: selected.bars_since_qualified13,
                      seconds: selected.elapsed_since_qualified13_seconds ?? "",
                    })}
              </dd>
            </div>
          </dl>
          {selected.next_conditions.length > 0 && (
            <>
              <h3>{text("demark.next")}</h3>
              <ul>
                {selected.next_conditions.map((c, i) => (
                  <li key={i}>
                    {labeled(text, "quote", c.field)} {c.operator} {c.threshold}{" "}
                    <small>({labeled(text, "purpose", c.purpose)})</small>
                  </li>
                ))}
              </ul>
            </>
          )}
          <details>
            <summary>{text("demark.evidence")}</summary>
            <p>
              {text("demark.setupBegan", {
                time: when(selected.setup_bars[0].close_time),
                perfected: when(selected.perfected_at),
              })}
            </p>
            <p>
              {text("demark.historicalRisk", {
                level: price(selected.risk_level),
                source: when(selected.risk_source?.close_time),
                ended: when(selected.risk_ended_at),
              })}
            </p>
            <p>
              {text("demark.tdstMeta", {
                source: when(selected.tdst_source?.close_time),
                breached: when(selected.tdst_breached_at),
              })}
            </p>
            <ol className="wh-td-events">
              {result.events
                .filter((e) => e.sequence_id === selected.sequence_id)
                .map((e, i) => (
                  <li key={i}>
                    {when(e.bar.close_time)} · {labeled(text, "kind", e.kind)}
                    {e.count !== null ? ` ${e.count}` : ""}
                    <br />
                    <small>
                      {e.reason.replaceAll("_", " ")} · {e.bar.revision_id.slice(0, 10)}
                    </small>
                  </li>
                ))}
            </ol>
          </details>
        </>
      )}
      <h3>{text("demark.scope")}</h3>
      <p>{text("demark.scopeCount", { count: result.qualified13_count })}</p>
      <p className="wh-muted">
        {when(result.history_start)} → {when(result.history_end)}
      </p>
      <ul>
        {result.issues.map((issue) => (
          <li key={issue}>{issueText(text, issue)}</li>
        ))}
      </ul>
      <details>
        <summary>{text("demark.rules")}</summary>
        <p>
          {text("demark.rulesBody", {
            version: result.config.ruleset_version,
            perfection: result.config.perfection_policy,
            sameSide: result.config.same_side_policy,
          })}
        </p>
        <p>
          {text("demark.rulesBreach", {
            tdst: result.config.tdst_breach,
            risk: result.config.risk_breach,
            recycling: result.config.recycling,
            expiry: result.config.validity_bars ?? text("demark.noneExpiry"),
          })}
        </p>
        <p>{text("demark.rulesRisk")}</p>
      </details>
    </>
  );
}
