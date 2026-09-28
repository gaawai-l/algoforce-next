import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getMarketContext,
  getWorkspace,
  money,
  stamp,
  submitJob,
  type Rules,
  type Stream,
} from "./client";
import { useWheelhouseText, type MessageKey } from "./i18n";
import {
  regimeSideFor,
  shortAge,
  signalLevel,
  type Board,
} from "./regime-board";
import type { MarketContext, TimeframeContext } from "./regime-contract";

import { useLiveMarketRefresh } from "./use-initial-market-refresh";

const durations: Record<string, number> = {
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

type Row = { key: MessageKey; cell: (tf: TimeframeContext) => string };

export function RegimeCheck({
  stream,
  rules,
  live = true,
}: {
  stream: Stream;
  rules: Rules;
  live?: boolean;
}) {
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const cache = useQueryClient();
  const [board, setBoard] = useState<Board>("cta");
  const [calibrate, setCalibrate] = useState({ intraday: true, swing: true });
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
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const refresh = useMutation({
    // `skip` is the page's own timeframe on auto refresh: the page already refreshes it.
    // Due when stale/delayed/unavailable OR fresh-but-incomplete history; simulated (fixture,
    // capped at 320 bars) can never complete history, so it is always excluded.
    mutationFn: async ({
      data,
      skip,
    }: {
      data: MarketContext;
      skip?: string;
    }) => {
      const due = data.timeframes.filter(
        (tf) =>
          (tf.status !== "fresh" ||
            !tf.history_complete ||
            (tf.last_closed_at &&
              Date.now() >=
                Date.parse(tf.last_closed_at) +
                  durations[tf.timeframe] * 1000 +
                  2000)) &&
          tf.status !== "simulated" &&
          tf.timeframe !== skip,
      );
      const results = await Promise.allSettled(
        due.map(async (tf) => {
          const selected = { ...stream, timeframe: tf.timeframe };
          const workspace = await getWorkspace(selected);
          if (
            ["queued", "running", "retry_wait"].includes(
              workspace.latest_job?.state ?? "",
            )
          )
            return;
          await submitJob(
            { kind: "refresh", stream: selected, rules },
            crypto.randomUUID(),
          );
        }),
      );
      const failed = results.find((result) => result.status === "rejected");
      if (failed?.status === "rejected") throw failed.reason;
    },
    onSuccess: () => setRefreshError(null),
    onError: (error) => setRefreshError(String((error as Error).message)),
    onSettled: () => cache.invalidateQueries({ queryKey: ["wh"] }),
  });
  useLiveMarketRefresh(
    `context:${stream.venue}:${stream.symbol}:${stream.timeframe}`,
    live &&
      !!context.data &&
      context.data.source === stream.source &&
      context.data.symbol === stream.symbol &&
      !refresh.isPending,
    async () => {
      if (context.data)
        await refresh.mutateAsync({
          data: context.data,
          skip: stream.timeframe,
        });
    },
  );

  const data = context.data;
  // Keys built from payload enums; the cast is only as safe as the enumeration test in
  // regime-check.test.tsx, which asserts every dynamic key this component can build exists
  // in messages.en (both catalogs share the same key set, checked by i18n.test.ts).
  const tk = (key: string, vars?: Parameters<typeof text>[1]) =>
    text(key as MessageKey, vars);
  const trendWord = (trend: "up" | "down") => tk(`regime.trend.${trend}`);
  const signalCell = (tf: TimeframeContext, n: 1 | 2) => {
    const signal = tf.signals.find((s) => s.n === n);
    if (!signal) return missing;
    const side = regimeSideFor(board, tf.timeframe);
    const level = signalLevel(signal, side, calibrate[side]);
    const label = `${signal.side.toUpperCase()} ${n}`;
    const price = signal.price
      ? money(signal.price, missing)
      : text("regime.signal.none");
    if (level == null) return `${label} · ${text("regime.signal.none")}`;
    // Calibration requested but its regime is unavailable: the level is the base level.
    const uncalibrated =
      calibrate[side] && data?.[side].value === "unavailable"
        ? ` · ${text("regime.level.uncalibrated")}`
        : "";
    return `${label} · ${price} · ${tk(`regime.level.${level}`)}${uncalibrated}`;
  };
  const reason = (tf: TimeframeContext) =>
    tf.status === "stale" || tf.status === "unavailable"
      ? tk(`regime.reason.${tf.status}`)
      : tf.history_gapped
        ? text("regime.reason.gapped")
        : !tf.history_complete
          ? text("regime.reason.short")
          : undefined;
  const rows: Row[] = [
    {
      key: "regime.row.data",
      cell: (tf) =>
        `${tk(`regime.status.${tf.status}`)} · ${stamp(tf.last_closed_at, missing)}`,
    },
    {
      key: "regime.row.nine",
      cell: (tf) =>
        !tf.state || !tf.summary
          ? missing
          : tf.state.s9 === "none"
            ? text("regime.s9.none", {
                trend: trendWord(tf.summary.trend),
                count: tf.summary.setup_step,
              })
            : tk(`regime.s9.${tf.state.s9}`),
    },
    {
      key: "regime.row.thirteen",
      cell: (tf) =>
        !tf.state
          ? missing
          : tf.state.s9 === "none"
            ? "—"
            : tf.state.s13
              ? text(
                  tf.state.s9 === "down"
                    ? "regime.s13.downDone"
                    : "regime.s13.upDone",
                )
              : text("regime.s13.pending", { count: tf.state.countdown }),
    },
    {
      key: "regime.row.setup",
      cell: (tf) =>
        tf.summary
          ? `${tf.summary.setup_run.side.toUpperCase()} ${tf.summary.setup_run.count}/9`
          : missing,
    },
    {
      key: "regime.row.since9",
      cell: (tf) =>
        !tf.state ? missing : (shortAge(tf.state.setup9_seconds_ago) ?? "—"),
    },
    {
      key: "regime.row.since13",
      cell: (tf) =>
        !tf.state
          ? missing
          : (shortAge(tf.state.qualified13_seconds_ago) ?? "—"),
    },
    {
      key: "regime.row.risk9",
      cell: (tf) => {
        if (!tf.summary) return missing;
        const risk9 = tf.summary.risk.risk9;
        if (risk9 == null) return "—";
        const sign = tf.summary.trend === "up" ? "<" : ">";
        const beyond = tf.state?.beyond_risk9;
        const note =
          beyond == null
            ? ""
            : ` · ${text(beyond ? "regime.beyond.yes" : "regime.beyond.no")}`;
        return `${sign} ${money(risk9, missing)}${note}`;
      },
    },
    {
      key: "regime.row.risk13",
      cell: (tf) => {
        if (!tf.summary) return missing;
        const risk = tf.summary.risk;
        if (risk.risk_level == null) return "—";
        const label = text(
          risk.provisional ? "regime.risk13.previous" : "regime.risk13.current",
        );
        const sign = tf.summary.trend === "up" ? "<" : ">";
        return `${label} ${sign} ${money(risk.risk_level, missing)}`;
      },
    },
    {
      key: "regime.row.next",
      cell: (tf) => {
        if (!tf.summary) return missing;
        const need = tf.summary.risk.next_bar_needs;
        if (need == null) return "—";
        return `${need.direction === "below" ? "<" : ">"} ${money(need.price, missing)}`;
      },
    },
    { key: "regime.row.signal1", cell: (tf) => signalCell(tf, 1) },
    { key: "regime.row.signal2", cell: (tf) => signalCell(tf, 2) },
    {
      key: "regime.row.newTrend",
      cell: (tf) => {
        const trend = tf.new_trend;
        if (!trend) return missing;
        if (!trend.present) return text("regime.newTrend.none");
        const vars = { trend: trendWord(trend.trend), count: trend.step };
        const body = text(
          trend.confirmed
            ? "regime.newTrend.confirmed"
            : "regime.newTrend.forming",
          vars,
        );
        const age = shortAge(trend.seconds);
        return age ? `${body} · ${age}` : body;
      },
    },
    {
      key: "regime.row.tdst",
      cell: (tf) =>
        !tf.summary
          ? missing
          : tf.summary.risk.tdst == null
            ? "—"
            : money(tf.summary.risk.tdst),
    },
    {
      key: "regime.row.window",
      cell: (tf) =>
        (tf.history_complete
          ? `${tf.bars_used}`
          : text("regime.window.short", {
              count: tf.bars_used,
              window: data?.window ?? 499,
            })) +
        (tf.history_gapped ? ` · ${text("regime.window.gapped")}` : ""),
    },
  ];
  const cellOf = (key: MessageKey, tf: TimeframeContext) =>
    rows.find((row) => row.key === key)?.cell(tf) ?? missing;
  const basis = (side: "intraday" | "swing") => {
    if (!data) return missing;
    const anchorTimeframe = data[side].anchor;
    const anchor = data.timeframes.find(
      (tf) => tf.timeframe === anchorTimeframe,
    );
    return anchor
      ? `${cellOf("regime.row.nine", anchor)} · ${cellOf("regime.row.thirteen", anchor)}`
      : missing;
  };

  return (
    <details className="wh-regime" open>
      <summary>{text("regime.title")}</summary>
      {context.error ? (
        <p className="wh-regime-error" role="alert">
          {String((context.error as Error).message)}
        </p>
      ) : !data ? (
        <p className="wh-regime-note">{text("service.connecting")}</p>
      ) : (
        <>
          <div className="wh-regime-head">
            {(["intraday", "swing"] as const).map((side) => (
              <div
                key={side}
                className={`wh-regime-pill is-${data[side].value}`}
              >
                <span>{tk(`regime.${side}`)}</span>
                <strong>{tk(`regime.value.${data[side].value}`)}</strong>
                <em>{basis(side)}</em>
                <label>
                  <input
                    type="checkbox"
                    checked={calibrate[side]}
                    onChange={(e) =>
                      setCalibrate((c) => ({ ...c, [side]: e.target.checked }))
                    }
                  />
                  {tk(`regime.calibrate.${side}`)}
                </label>
              </div>
            ))}
            <div
              className="wh-regime-boards"
              role="radiogroup"
              aria-label={text("regime.boardGroup")}
            >
              {(["cta", "opt", "all"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="radio"
                  aria-checked={board === item}
                  className={board === item ? "is-active" : ""}
                  onClick={() => setBoard(item)}
                >
                  {tk(`regime.board.${item}`)}
                </button>
              ))}
            </div>
          </div>
          {refreshError ? (
            <p className="wh-regime-error" role="alert">
              {text("regime.refreshFailed")}: {refreshError}
            </p>
          ) : null}
          <p className="wh-regime-note">
            {text("regime.note", { window: data.window })}
          </p>
          <div className="wh-regime-scroll">
            <table className="wh-regime-table">
              <thead>
                <tr>
                  <th scope="col" />
                  {data.timeframes.map((tf) => (
                    <th key={tf.timeframe} scope="col">
                      {tf.timeframe.toUpperCase()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row">{text(row.key)}</th>
                    {data.timeframes.map((tf) => (
                      <td key={tf.timeframe} title={reason(tf)}>
                        {row.cell(tf)}
                      </td>
                    ))}
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
