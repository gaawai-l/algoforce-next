import { useQuery } from "@tanstack/react-query";
import { getMarketCycle } from "./client";
import type { MarketCycle } from "./cycle-contract";
import { useWheelhouseText, type MessageKey } from "./i18n";

type Components = NonNullable<MarketCycle["index"]>["components"];
const COMPONENTS: (keyof Components)[] = [
  "unrealized",
  "realized",
  "supply",
  "young_vs_seasoned",
];
const CHANGES = ["1d", "7d", "30d", "90d"];

const pct = (value: number) => (value * 100).toFixed(1);
const signed = (value: number | null | undefined) =>
  value == null ? "—" : `${value > 0 ? "+" : ""}${Math.round(value)}`;

/** Check view for AlphaBTC's on-chain cycle (BTC only); final UI is designed separately. */
export function CycleCheck() {
  const { text } = useWheelhouseText();
  const tk = (key: string) => text(key as MessageKey);
  const cycle = useQuery({
    queryKey: ["wh", "market-cycle"],
    queryFn: ({ signal }) => getMarketCycle(signal),
    refetchInterval: 15 * 60 * 1000,
    retry: false,
  });
  const data = cycle.data;
  const states = data?.states;
  const index = data?.index;
  const pressure = data?.pressure;

  return (
    <details className="wh-regime" open>
      <summary>{text("cycleCheck.title")}</summary>
      {cycle.error ? (
        <p className="wh-regime-error" role="alert">
          {String((cycle.error as Error).message)}
        </p>
      ) : !data ? (
        <p className="wh-regime-note">{text("service.connecting")}</p>
      ) : data.status === "unavailable" || !states || !index || !pressure ? (
        <p className="wh-regime-error" role="alert">
          {text("cycleCheck.unavailable")}
          {data.error ? `: ${data.error}` : ""}
        </p>
      ) : (
        <>
          <div className="wh-regime-head">
            <div className="wh-regime-pill">
              <span>{text("cycleCheck.stateLabel")}</span>
              <strong>{tk(`cycleCheck.state.${states.state}`)}</strong>
              <em>
                {text("cycleCheck.stateValue", {
                  state: tk(`cycleCheck.state.${states.state}`),
                  days: states.days,
                  since: states.since,
                })}
              </em>
            </div>
            <div className="wh-regime-pill">
              <span>{text("cycleCheck.indexLabel")}</span>
              <strong>{Math.round(index.composite)}</strong>
              <em>{tk(`cycleCheck.zone.${index.zone}`)}</em>
            </div>
            <div className="wh-regime-pill">
              <span>{text("cycleCheck.pressureLabel")}</span>
              <strong>
                {text("cycleCheck.pressureValue", {
                  value: pressure.value.toFixed(1),
                  stage: tk(`cycleCheck.stage.${pressure.stage}`),
                })}
              </strong>
              <em>
                {text("cycleCheck.pressureLines", {
                  warn: pressure.warn,
                  confirm: pressure.confirm,
                })}
              </em>
            </div>
          </div>
          {data.status === "stale" ? (
            <p className="wh-regime-error" role="alert">
              {text("cycleCheck.status.stale")}
            </p>
          ) : null}
          <p className="wh-regime-note">
            {text("cycleCheck.note", { day: data.as_of ?? "—" })}
          </p>
          <div className="wh-regime-scroll">
            <table className="wh-regime-table">
              <tbody>
                {COMPONENTS.map((key) => (
                  <tr key={key}>
                    <th scope="row">{tk(`cycleCheck.component.${key}`)}</th>
                    <td>{Math.round(index.components[key])}</td>
                  </tr>
                ))}
                <tr>
                  <th scope="row">{text("cycleCheck.composite")}</th>
                  <td>{Math.round(index.composite)}</td>
                </tr>
                <tr>
                  <th scope="row">{text("cycleCheck.change")}</th>
                  <td>
                    {CHANGES.map((key) => signed(index.change[key])).join(
                      " / ",
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="wh-regime-note">
            {text("cycleCheck.stats.note", {
              changes: states.changes,
              multiplier: states.multiplier,
              depth: pct(states.depth),
              spread: pct(states.spread),
            })}
          </p>
          <div className="wh-regime-scroll">
            <table className="wh-regime-table">
              <thead>
                <tr>
                  <th scope="col">{text("cycleCheck.stats.state")}</th>
                  <th scope="col">{text("cycleCheck.stats.runs")}</th>
                  <th scope="col">{text("cycleCheck.stats.days")}</th>
                  <th scope="col">{text("cycleCheck.stats.mean")}</th>
                  <th scope="col">{text("cycleCheck.stats.median")}</th>
                  <th scope="col">{text("cycleCheck.stats.max")}</th>
                </tr>
              </thead>
              <tbody>
                {states.stats.map((row) => (
                  <tr
                    key={row.state}
                    aria-current={row.state === states.state || undefined}
                  >
                    <th scope="row">{tk(`cycleCheck.state.${row.state}`)}</th>
                    <td>{row.runs}</td>
                    <td>{row.days}</td>
                    <td>{row.mean_days ?? "—"}</td>
                    <td>{row.median_days ?? "—"}</td>
                    <td>{row.max_days ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </details>
  );
}
