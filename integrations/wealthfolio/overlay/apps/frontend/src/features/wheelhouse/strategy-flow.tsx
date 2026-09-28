import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getMarketContext, type Stream } from "./client";
import { useWheelhouseText, type MessageKey } from "./i18n";
import {
  BACKTEST,
  LEGS,
  PHASES,
  RISK_ROWS,
  SIDES,
  actionOf,
  currentPattern,
  loadState,
  nextAction,
  nextRiskDir,
  riskOf,
  saveState,
  selectablePatterns,
  type Copy,
  type FlowState,
} from "./strategy-flow-data";

/** AlphaBTC ④–⑧: hand-picked cycle phase, pattern and option/risk actions (check view). */
export function StrategyFlow({ stream }: { stream: Stream }) {
  const { locale, text } = useWheelhouseText();
  const tk = (key: string) => text(key as MessageKey);
  const say = (copy: Copy) => copy[locale];
  const [state, setState] = useState<FlowState>(loadState);
  useEffect(() => saveState(state), [state]);
  const context = useQuery({
    queryKey: [
      "wh",
      "market-context",
      stream.source,
      stream.venue,
      stream.symbol,
    ],
    queryFn: ({ signal }) =>
      getMarketContext(stream.source, stream.symbol, signal),
    refetchInterval: 30000,
    retry: false,
  });

  const phase = PHASES.find((p) => p.id === state.phase) ?? PHASES[1];
  const patterns = selectablePatterns(phase);
  const pattern = currentPattern(state);
  const backtest = BACKTEST[state.backtest];
  const update = (fn: (s: FlowState) => FlowState) => setState((s) => fn(s));

  return (
    <details className="wh-regime" open>
      <summary>{text("flow.title")}</summary>
      <p className="wh-regime-note">{text("flow.note")}</p>

      <h3 className="wh-flow-step">{text("flow.phase")}</h3>
      <div
        className="wh-regime-boards"
        role="radiogroup"
        aria-label={text("flow.phase")}
      >
        {PHASES.map((p) => (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={p.id === phase.id}
            className={p.id === phase.id ? "is-active" : ""}
            onClick={() => update((s) => ({ ...s, phase: p.id }))}
          >
            {say(p.name)}
          </button>
        ))}
      </div>
      <p className="wh-regime-note">
        {[phase.state && say(phase.state), phase.skew]
          .filter(Boolean)
          .join(" · ") || "—"}
      </p>

      <h3 className="wh-flow-step">{text("flow.pattern")}</h3>
      {patterns.length === 0 ? (
        <p className="wh-regime-note">{text("flow.undefined")}</p>
      ) : (
        <div
          className="wh-regime-boards"
          role="radiogroup"
          aria-label={text("flow.pattern")}
        >
          {patterns.map((p) => (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={p.id === pattern?.id}
              className={p.id === pattern?.id ? "is-active" : ""}
              onClick={() =>
                update((s) => ({
                  ...s,
                  pattern: { ...s.pattern, [phase.id]: p.id },
                }))
              }
            >
              {p.when ? `${say(p.when)} · ${say(p.label)}` : say(p.label)}
            </button>
          ))}
        </div>
      )}
      {pattern ? (
        <p className="wh-regime-note">
          {pattern.headline ? `${say(pattern.headline)} · ` : ""}
          {text("flow.model")}:{" "}
          {pattern.model ? say(pattern.model) : text("flow.undefined")}
        </p>
      ) : null}

      <h3 className="wh-flow-step">{text("flow.options")}</h3>
      {!pattern?.acts || !pattern.options ? (
        <p className="wh-regime-note">{text("flow.undefined")}</p>
      ) : (
        <>
          <div className="wh-regime-head">
            {SIDES.map((side) => {
              const regime = context.data?.[side.anchor].value;
              return (
                <div key={side.id} className="wh-regime-pill">
                  <span>{tk(`flow.side.${side.id}`)}</span>
                  <em>
                    {regime ? tk(`regime.value.${regime}`) : text("missing")}
                  </em>
                  {side.rows.flat().map((leg) => {
                    const key = `${side.id}:${leg}` as const;
                    const action = actionOf(state, pattern, side.id, leg)!;
                    const selected = state.actSel[pattern.id]?.[key] === true;
                    return (
                      <div key={leg} className="wh-flow-item">
                        <button
                          type="button"
                          aria-pressed={selected}
                          className={selected ? "is-active" : ""}
                          onClick={() =>
                            update((s) => ({
                              ...s,
                              actSel: {
                                ...s.actSel,
                                [pattern.id]: {
                                  ...s.actSel[pattern.id],
                                  [key]: !selected,
                                },
                              },
                            }))
                          }
                        >
                          {tk(`flow.leg.${leg}`)}
                        </button>
                        <button
                          type="button"
                          className={`wh-flow-action is-${action}`}
                          onClick={() =>
                            update((s) => ({
                              ...s,
                              act: {
                                ...s.act,
                                [pattern.id]: {
                                  ...s.act[pattern.id],
                                  [key]: nextAction(action),
                                },
                              },
                            }))
                          }
                        >
                          {tk(`flow.action.${action}`)}
                        </button>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
          <p className="wh-regime-note">
            {pattern.options.lead ? `${say(pattern.options.lead)} · ` : ""}
            {say(pattern.options.text)}
          </p>
        </>
      )}

      <h3 className="wh-flow-step">{text("flow.risk")}</h3>
      {!pattern?.risk ? (
        <p className="wh-regime-note">{text("flow.undefined")}</p>
      ) : (
        <>
          <div className="wh-regime-head">
            {RISK_ROWS.map((row) => (
              <div key={row} className="wh-regime-pill">
                <span>{tk(`flow.riskRow.${row}`)}</span>
                {LEGS.map((leg) => {
                  const item = riskOf(state, pattern, row, leg);
                  const key = `${row}:${leg}` as const;
                  const set = (next: typeof item) =>
                    update((s) => ({
                      ...s,
                      risk: {
                        ...s.risk,
                        [pattern.id]: { ...s.risk[pattern.id], [key]: next },
                      },
                    }));
                  return (
                    <div key={leg} className="wh-flow-item">
                      <button
                        type="button"
                        aria-pressed={item.sel}
                        className={item.sel ? "is-active" : ""}
                        onClick={() => set({ ...item, sel: !item.sel })}
                      >
                        {tk(`flow.leg.${leg}`)}
                      </button>
                      <button
                        type="button"
                        className={`wh-flow-action is-${item.dir}`}
                        onClick={() =>
                          set({ ...item, dir: nextRiskDir(row, item.dir) })
                        }
                      >
                        {tk(`flow.dir.${item.dir}`)}
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <p className="wh-regime-note">
            {say(pattern.risk.text)}
            {pattern.risk.pending ? ` · ${say(pattern.risk.pending)}` : ""}
          </p>
        </>
      )}

      <h3 className="wh-flow-step">{text("flow.backtest")}</h3>
      <div
        className="wh-regime-boards"
        role="radiogroup"
        aria-label={text("flow.backtest")}
      >
        {(["put", "call"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            role="radio"
            aria-checked={state.backtest === kind}
            className={state.backtest === kind ? "is-active" : ""}
            onClick={() => update((s) => ({ ...s, backtest: kind }))}
          >
            {tk(`flow.backtest.${kind}`)}
          </button>
        ))}
      </div>
      <p className="wh-regime-note">
        {say(backtest.lead)} · {say(backtest.hint)} ·{" "}
        {text("flow.backtestNote")}
      </p>
      <div className="wh-regime-scroll">
        <table className="wh-regime-table">
          <thead>
            <tr>
              <th scope="col">{text("flow.backtest.tf")}</th>
              <th scope="col">{text("flow.backtest.w80")}</th>
              <th scope="col">{text("flow.backtest.w70")}</th>
              <th scope="col">{text("flow.backtest.w60")}</th>
            </tr>
          </thead>
          <tbody>
            {backtest.rows.map((row) => (
              <tr key={row.tf.en}>
                <th scope="row">{say(row.tf)}</th>
                {row.cells.map((cell, i) => (
                  <td key={i} className={row.na?.includes(i) ? "is-muted" : ""}>
                    {say(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
