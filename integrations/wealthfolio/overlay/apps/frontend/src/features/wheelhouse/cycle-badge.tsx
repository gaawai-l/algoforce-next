import { useQuery } from "@tanstack/react-query";
import { getOnchainCycle, type Stream } from "./client";
import { messages, useWheelhouseText, type MessageKey } from "./i18n";
import { shortDay as formatDay } from "./onchain-levels";
import { rulesNote } from "./onchain-text";

export function CycleBadge({
  symbol,
  live,
  onOpen,
}: {
  symbol: Stream["symbol"];
  live: boolean;
  onOpen: () => void;
}) {
  const { locale, text } = useWheelhouseText();
  const shown = symbol === "BTCUSDT" && live;
  const cycle = useQuery({
    queryKey: ["wh", "onchain", "cycle"],
    queryFn: ({ signal }) => getOnchainCycle(signal),
    refetchInterval: 60000,
    retry: false,
    enabled: shown,
  });
  if (!shown) return null;

  // Keys built from payload enums; every one of them exists in both catalogs.
  const tk = (key: string, vars?: Parameters<typeof text>[1]) =>
    text(key as MessageKey, vars);
  const shortDay = (day: string) => formatDay(text, locale, day);
  const reasonText = (reason: string) => {
    const series = /^series_missing:(.+)$/.exec(reason);
    if (series) return text("cycle.reason.seriesMissing", { name: series[1] });
    const key = `cycle.reason.${reason}`;
    return Object.prototype.hasOwnProperty.call(messages.en, key)
      ? tk(key)
      : reason;
  };

  const data = cycle.data;
  // A failed request wins over older data: the badge must not look current when it is not,
  // whatever the error says (it may have no message at all).
  const failed = cycle.isError;
  const failure = failed ? String((cycle.error as Error).message ?? "") : "";
  if (!data && !failed) return null;
  if (
    failed ||
    !data ||
    data.data_state === "unavailable" ||
    !data.state ||
    data.day == null ||
    !data.as_of
  ) {
    const reason = failed ? failure : data?.reasons.map(reasonText).join(" · ");
    return (
      <button
        type="button"
        className="wh-cycle wh-cycle--muted"
        title={text("cycle.open")}
        onClick={onOpen}
      >
        <span className="wh-cycle-main">{text("cycle.unavailable")}</span>
        {reason ? <small>{reason}</small> : null}
      </button>
    );
  }

  const stale = data.data_state === "stale";
  return (
    <button
      type="button"
      className={stale ? "wh-cycle wh-cycle--muted" : "wh-cycle"}
      title={[text("cycle.open"), ...rulesNote(text, data)].join("\n")}
      onClick={onOpen}
    >
      <span className="wh-cycle-main">
        {text("cycle.label", {
          state: tk(`cycle.state.${data.state}`),
          day: data.day,
        })}
      </span>
      {data.since ? (
        <small>{text("cycle.since", { date: shortDay(data.since) })}</small>
      ) : null}
      {stale ? (
        <small>{text("cycle.stale", { date: shortDay(data.as_of) })}</small>
      ) : data.forming_at ? (
        <small>{text("cycle.forming")}</small>
      ) : null}
    </button>
  );
}
