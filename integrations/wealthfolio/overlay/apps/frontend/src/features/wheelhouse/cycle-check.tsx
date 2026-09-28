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
      <summary>{text("cycle.title")}</summary>
      {cycle.error ? (
        <p className="wh-regime-error" role="alert">
          {String((cycle.error as Error).message)}
        </p>
      ) : !data ? (
        <p className="wh-regime-note">{text("service.connecting")}</p>
      ) : data.status === "unavailable" || !states || !index || !pressure ? (
        <p className="wh-regime-error" role="alert">
          {text("cycle.unavailable")}
          {data.error ? `: ${data.error}` : ""}
        </p>
      ) : (
        <>
          <div className="wh-regime-head">
            <div className="wh-regime-pill">
              <span>{text("cycle.stateLabel")}</span>
              <strong>{tk(`cycle.state.${states.state}`)}</strong>
              <em>
                {text("cycle.stateValue", {
                  state: tk(`cycle.state.${states.state}`),
                  days: states.days,
                  since: states.since,
                })}
              </em>
            </div>
            <div className="wh-regime-pill">
              <span>{text("cycle.indexLabel")}</span>
              <strong>{Math.round(index.composite)}</strong>
              <em>{tk(`cycle.zone.${index.zone}`)}</em>
            </div>
            <div className="wh-regime-pill">
              <span>{text("cycle.pressureLabel")}</span>
              <strong>
                {text("cycle.pressureValue", {
                  value: pressure.value.toFixed(1),
                  stage: tk(`cycle.stage.${pressure.stage}`),
                })}
              </strong>
              <em>
                {text("cycle.pressureLines", {
                  warn: pressure.warn,
                  confirm: pressure.confirm,
                })}
              </em>
            </div>
          </div>
          {data.status === "stale" ? (
            <p className="wh-regime-error" role="alert">
              {text("cycle.status.stale")}
            </p>
          ) : null}
          <p className="wh-regime-note">
            {text("cycle.note", { day: data.as_of ?? "—" })}
          </p>
          <div className="wh-regime-scroll">
            <table className="wh-regime-table">
              <tbody>
                {COMPONENTS.map((key) => (
                  <tr key={key}>
                    <th scope="row">{tk(`cycle.component.${key}`)}</th>
                    <td>{Math.round(index.components[key])}</td>
                  </tr>
                ))}
                <tr>
                  <th scope="row">{text("cycle.composite")}</th>
                  <td>{Math.round(index.composite)}</td>
                </tr>
                <tr>
                  <th scope="row">{text("cycle.change")}</th>
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
            {text("cycle.stats.note", {
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
                  <th scope="col">{text("cycle.stats.state")}</th>
                  <th scope="col">{text("cycle.stats.runs")}</th>
                  <th scope="col">{text("cycle.stats.days")}</th>
                  <th scope="col">{text("cycle.stats.mean")}</th>
                  <th scope="col">{text("cycle.stats.median")}</th>
                  <th scope="col">{text("cycle.stats.max")}</th>
                </tr>
              </thead>
              <tbody>
                {states.stats.map((row) => (
                  <tr
                    key={row.state}
                    aria-current={row.state === states.state || undefined}
                  >
                    <th scope="row">{tk(`cycle.state.${row.state}`)}</th>
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
