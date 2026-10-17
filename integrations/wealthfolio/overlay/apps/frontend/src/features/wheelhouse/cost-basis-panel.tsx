import { useId, type ReactNode } from "react";
import { usd } from "./client";
import { useWheelhouseText, type MessageKey, type TextFn } from "./i18n";
import type { RailBand } from "./levels-rail";
import type { BucketCostBasis, CostBasisView } from "./onchain-contract";
import { lineNameKey, reasonText, utcDay } from "./onchain-text";

export type CostBucket = BucketCostBasis["bucket"];
type Cohort = "sth" | "lth";
type Band = BucketCostBasis["above"][number];
type Candidate = Band["candidates"][number];

const NTH: MessageKey[] = [
  "costBasis.nth1",
  "costBasis.nth2",
  "costBasis.nth3",
  "costBasis.nth4",
];
const EDGE = { low: " −σ", mid: "", high: " +σ" } as const;
const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumSignificantDigits: 3,
});

// The service counts every row from its fixed MIN_PRICE of $1k, whatever the bucket's domain.
const LEGEND_FLOOR = "$1k";

// $86.0k
const kUsd = (price: number) => `$${(price / 1000).toFixed(1)}k`;

// The older of two UTC days: a reading is as old as its oldest input.
const olderDay = (a: string | null, b: string | null) =>
  a && b ? (a < b ? a : b) : (a ?? b);

// A missing bucket is explained by the codes without a width and those of its own width.
const forBucket = (bucket: CostBucket) => (reason: string) => {
  const agg = /:(lin\d+)$/.exec(reason)?.[1];
  return !agg || agg === `lin${bucket}`;
};

// From spot to the band's midpoint, one decimal, signed with a true minus.
function fromSpot(band: Band, spot: number) {
  const pct = Math.round(((band.low + band.high) / 2 / spot - 1) * 1000) / 10;
  return `${pct < 0 ? "−" : "+"}${Math.abs(pct).toFixed(1)}%`;
}

// A model line by its name; a component as "STH M2", "STH M2 −σ" or "STH M2 +σ".
const candidateLabel = (text: TextFn, candidate: Candidate) =>
  candidate.kind === "line" && candidate.line
    ? text(lineNameKey[candidate.line])
    : `${candidate.cohort?.toUpperCase()} M${candidate.index}${candidate.edge ? EDGE[candidate.edge] : ""}`;

// The selected bucket's peaks as rail bands; a cohort switched off draws nothing.
export function railBands(
  bucket: BucketCostBasis | undefined,
  show: Record<Cohort, boolean>,
): RailBand[] {
  if (!bucket) return [];
  return (["sth", "lth"] as const)
    .filter((cohort) => show[cohort])
    .flatMap((cohort) =>
      bucket[cohort].peaks.map((peak, i) => ({
        id: `${cohort}-${i + 1}`,
        cohort,
        index: i + 1,
        price: peak.price,
        low: peak.price - peak.width / 2,
        high: peak.price + peak.width / 2,
        strength: peak.strength,
        btc: peak.btc,
        share: peak.share,
      })),
    );
}

// "3.66M BTC ≥$1k · 62% in profit": the cohort's coins from the service's fixed $1k floor.
export function bandsLegend(
  text: TextFn,
  bucket: BucketCostBasis,
  cohort: Cohort,
  stale: boolean,
) {
  const { total, in_profit } = bucket[cohort];
  const legend = text("costBasis.legend", {
    btc: compact.format(total),
    floor: LEGEND_FLOOR,
    profit: in_profit == null ? "—" : `${Math.round(in_profit * 100)}%`,
  });
  return stale ? text("costBasis.legendStale", { legend }) : legend;
}

export function CostBasisPanel({
  view,
  error,
  bucket,
}: {
  view?: CostBasisView;
  // A failed request wins over older data, so a failure never looks like a current reading.
  error?: string;
  bucket: CostBucket;
}) {
  const { text } = useWheelhouseText();
  const id = useId();
  const reasonLine = (reasons: string[]) =>
    reasons.length ? (
      <p className="wh-muted">
        {reasons.map((reason) => reasonText(text, reason)).join(" · ")}
      </p>
    ) : null;

  let body: ReactNode;
  if (error)
    body = (
      <>
        <p className="wh-onchain-warn">{text("costBasis.unavailable")}</p>
        <p className="wh-muted">{error}</p>
      </>
    );
  else if (!view)
    body = <p className="wh-muted">{text("costBasis.loading")}</p>;
  else if (view.data_state === "unavailable")
    body = (
      <>
        <p className="wh-onchain-warn">{text("costBasis.unavailable")}</p>
        {reasonLine(view.reasons)}
      </>
    );
  else {
    const selected = view.buckets.find((b) => b.bucket === bucket);
    const bandRow = (side: "above" | "below", band: Band, spot: number) => (
      <tr key={`${side}-${band.low}`}>
        <th scope="row">
          {text(side === "above" ? "costBasis.above" : "costBasis.below")}
        </th>
        <td>
          <span className="wh-cb-range">
            {usd(band.low)} – {usd(band.high)}
          </span>
          <span className="wh-cb-labels">
            {band.candidates.map((c) => candidateLabel(text, c)).join(", ")}
          </span>
        </td>
        <td>{band.candidates.length}</td>
        <td>{fromSpot(band, spot)}</td>
      </tr>
    );
    body = (
      <>
        {view.data_state === "stale" ? (
          <p className="wh-onchain-warn">
            {text("cycle.stale", {
              date:
                olderDay(view.urpd_date, view.lines_as_of) ?? text("missing"),
            })}
          </p>
        ) : null}
        {view.forming_at ? (
          <p className="wh-muted">
            {text("costBasis.forming", { date: utcDay(view.forming_at) })}
          </p>
        ) : null}
        {selected ? (
          <>
            <table
              className="wh-cb-table wh-cb-levels"
              aria-labelledby={`${id}-levels`}
            >
              <thead>
                <tr>
                  <td />
                  {NTH.map((key) => (
                    <th key={key} scope="col">
                      {text(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["costBasis.resistance", selected.resistance],
                    ["costBasis.support", selected.support],
                  ] as const
                ).map(([key, prices]) => (
                  <tr key={key}>
                    <th scope="row">{text(key)}</th>
                    {NTH.map((_, i) => (
                      <td key={i}>
                        {prices[i] == null ? "—" : kUsd(prices[i])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 id={`${id}-nearest`}>{text("costBasis.nearestTitle")}</h3>
            <table
              className="wh-cb-table wh-cb-bands"
              aria-labelledby={`${id}-nearest`}
            >
              <thead>
                <tr>
                  <th scope="col">{text("costBasis.side")}</th>
                  <th scope="col">{text("costBasis.band")}</th>
                  <th scope="col">{text("costBasis.count")}</th>
                  <th scope="col">{text("costBasis.fromSpot")}</th>
                </tr>
              </thead>
              <tbody>
                {[...selected.above]
                  .reverse()
                  .map((band) => bandRow("above", band, selected.spot))}
                <tr className="is-spot">
                  <th scope="row">{text("costBasis.spot")}</th>
                  <td>
                    <span className="wh-cb-range">{usd(selected.spot)}</span>
                    <span className="wh-cb-labels">
                      {view.rules.includes("O1") && view.urpd_date
                        ? // Under O1 spot is the close of the snapshot's day, not a current price.
                          text("costBasis.spotClose", { date: view.urpd_date })
                        : text("costBasis.spotNote")}
                    </span>
                  </td>
                  <td />
                  <td>—</td>
                </tr>
                {selected.below.map((band) =>
                  bandRow("below", band, selected.spot),
                )}
              </tbody>
            </table>
            <p className="wh-muted">{text("costBasis.mNote")}</p>
          </>
        ) : (
          <p className="wh-onchain-warn">{text("costBasis.bucketMissing")}</p>
        )}
        {reasonLine(
          selected ? view.reasons : view.reasons.filter(forBucket(bucket)),
        )}
      </>
    );
  }

  return (
    <>
      <h3 id={`${id}-levels`}>{text("costBasis.levelsTitle")}</h3>
      {body}
      {!error && view?.refreshing ? (
        <p role="status">{text("costBasis.refreshing")}</p>
      ) : null}
    </>
  );
}
