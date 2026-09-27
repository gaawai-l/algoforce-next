import { useState } from "react";
import type { DemarkResult, DemarkSequence } from "./demark-contract";
import { stamp } from "./client";

export const exactPrice = (value: string | null | undefined) =>
  value ?? "Unavailable";
export const sequenceLabel = (s: DemarkSequence) =>
  `${s.side === "buy" ? "Buy · downward move" : "Sell · upward move"} · ${s.countdown_status === "inactive" ? `Setup ${s.setup_count}/9` : `Countdown ${s.countdown_count}/13`} · ${s.countdown_status === "inactive" ? s.setup_status : s.countdown_status === "qualified13" ? `qualified13 / risk ${s.risk_status}` : s.countdown_status.replaceAll("_", " ")}`;

export function DemarkDetails({
  result,
  selectedId,
  onSelect,
}: {
  result: DemarkResult | null | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [showHistory, setShowHistory] = useState(false);
  if (!result)
    return (
      <p>
        DeMark was not calculated in this snapshot. Refresh market data or run
        historical replay to calculate Sequential from the stored bars.
      </p>
    );
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
        SEQUENTIAL · {result.status.replaceAll("_", " ").toUpperCase()}
      </span>
      <p>
        Buy counts a downward move; Sell counts an upward move. A qualified 13
        is an exhaustion candidate, not a confirmed reversal.
      </p>
      <label className="wh-inline">
        <input
          type="checkbox"
          checked={showHistory}
          onChange={(e) => setShowHistory(e.target.checked)}
        />{" "}
        Include ended sequences
      </label>
      <label className="wh-td-picker">
        Sequence
        <select
          aria-label="DeMark sequence"
          value={selected?.sequence_id ?? ""}
          onChange={(e) => onSelect(e.target.value)}
        >
          {!selected && <option value="">No observed sequence</option>}
          {selected && !options.includes(selected) && (
            <option value={selected.sequence_id}>
              {sequenceLabel(selected)} · historical
            </option>
          )}
          {options.map((s) => (
            <option key={s.sequence_id} value={s.sequence_id}>
              {sequenceLabel(s)} ·{" "}
              {stamp(s.setup_bars[0].close_time).slice(0, 16)}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <>
          <h3>{selected.side === "buy" ? "Buy sequence" : "Sell sequence"}</h3>
          <dl className="wh-facts">
            <div>
              <dt>Setup</dt>
              <dd>
                {selected.setup_count}/9 · {selected.setup_status}
              </dd>
            </div>
            <div>
              <dt>Perfection</dt>
              <dd>
                {selected.setup_perfected === null
                  ? "Unknown / not completed"
                  : selected.setup_perfected
                    ? "Perfected"
                    : "Awaiting perfection"}
              </dd>
            </div>
            <div>
              <dt>Countdown</dt>
              <dd>
                {selected.countdown_count}/13 ·{" "}
                {selected.countdown_status === "count13_unqualified"
                  ? "13 deferred (+)"
                  : selected.countdown_status.replaceAll("_", " ")}
              </dd>
            </div>
            <div>
              <dt>Continuity</dt>
              <dd>
                {selected.continuity === "lost"
                  ? "Unknown after a gap"
                  : "Observed within input window"}
              </dd>
            </div>
            <div>
              <dt>TDST {selected.side === "buy" ? "resistance" : "support"}</dt>
              <dd>{exactPrice(selected.tdst)}</dd>
            </div>
            <div>
              <dt>Countdown 8 close</dt>
              <dd>{exactPrice(selected.qualification_threshold)}</dd>
            </div>
            <div>
              <dt>Risk Level · {selected.risk_status.replaceAll("_", " ")}</dt>
              <dd>
                {selected.risk_status === "valid"
                  ? exactPrice(selected.risk_level)
                  : "Inactive / unavailable"}
              </dd>
            </div>
            <div>
              <dt>Qualified 13 at</dt>
              <dd>{stamp(selected.qualified_at)}</dd>
            </div>
            <div>
              <dt>Confirmation close</dt>
              <dd>{exactPrice(selected.confirmation_close)}</dd>
            </div>
            <div>
              <dt>Since Setup 9</dt>
              <dd>
                {selected.bars_since_setup9 === null
                  ? "—"
                  : `${selected.bars_since_setup9} bars · ${selected.elapsed_since_setup9_seconds}s`}
              </dd>
            </div>
            <div>
              <dt>Since qualified 13</dt>
              <dd>
                {selected.bars_since_qualified13 === null
                  ? "—"
                  : `${selected.bars_since_qualified13} bars · ${selected.elapsed_since_qualified13_seconds}s`}
              </dd>
            </div>
          </dl>
          {selected.next_conditions.length > 0 && (
            <>
              <h3>Next closed bar · all conditions</h3>
              <ul>
                {selected.next_conditions.map((c, i) => (
                  <li key={i}>
                    {c.field} {c.operator} {c.threshold}{" "}
                    <small>({c.purpose})</small>
                  </li>
                ))}
              </ul>
            </>
          )}
          <details>
            <summary>Sequence evidence & events</summary>
            <p>
              Setup began {stamp(selected.setup_bars[0].close_time)}. Perfected{" "}
              {stamp(selected.perfected_at)}.
            </p>
            <p>
              Historical Risk Level: {exactPrice(selected.risk_level)}; source{" "}
              {stamp(selected.risk_source?.close_time)}. Ended{" "}
              {stamp(selected.risk_ended_at)}.
            </p>
            <p>
              TDST source {stamp(selected.tdst_source?.close_time)}. Breached{" "}
              {stamp(selected.tdst_breached_at)}.
            </p>
            <ol className="wh-td-events">
              {result.events
                .filter((e) => e.sequence_id === selected.sequence_id)
                .map((e, i) => (
                  <li key={i}>
                    {stamp(e.bar.close_time)} · {e.kind.replaceAll("_", " ")}
                    {e.count !== null ? ` ${e.count}` : ""}
                    <br />
                    <small>
                      {e.reason.replaceAll("_", " ")} ·{" "}
                      {e.bar.revision_id.slice(0, 10)}
                    </small>
                  </li>
                ))}
            </ol>
          </details>
        </>
      )}
      <h3>Calculation scope</h3>
      <p>
        {result.qualified13_count} qualified 13 events in this input window.
        Prior history is unknown.
      </p>
      <p className="wh-muted">
        {stamp(result.history_start)} → {stamp(result.history_end)}
      </p>
      <ul>
        {result.issues.map((issue) => (
          <li key={issue}>{issue}</li>
        ))}
      </ul>
      <details>
        <summary>Rules & variant</summary>
        <p>
          {result.config.ruleset_version}. Strict perfection; 13-vs-8 required;
          optional 8-vs-5 disabled.
        </p>
        <p>
          TDST breach: {result.config.tdst_breach}. Risk breach:{" "}
          {result.config.risk_breach}. Recycling: {result.config.recycling}.
          Expiry: {result.config.validity_bars ?? "None"}.
        </p>
        <p>
          Risk uses the true extreme in the Countdown span, with the earliest
          tie. Risk and recycling details are declared Wheelhouse policies, not
          a claim of proprietary platform equivalence.
        </p>
      </details>
    </>
  );
}
