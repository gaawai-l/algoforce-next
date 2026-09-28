import { useQuery } from "@tanstack/react-query";
import { getMacroWatch } from "./client";
import { useWheelhouseText } from "./i18n";

/** Rate-expectation inputs AlphaBTC leaves unfilled; check view, final UI designed separately. */
export function MacroCheck() {
  const { text } = useWheelhouseText();
  const macro = useQuery({
    queryKey: ["wh", "macro-watch"],
    queryFn: ({ signal }) => getMacroWatch(signal),
    refetchInterval: 60 * 1000,
    retry: false,
  });
  const data = macro.data;
  const fomc = data?.fomc;
  const spread = data?.spread;
  const left = fomc ? Date.parse(fomc.decision_at) - Date.now() : null;

  return (
    <details className="wh-regime" open>
      <summary>{text("macro.title")}</summary>
      {macro.error ? (
        <p className="wh-regime-error" role="alert">
          {String((macro.error as Error).message)}
        </p>
      ) : !data ? (
        <p className="wh-regime-note">{text("service.connecting")}</p>
      ) : (
        <div className="wh-regime-head">
          <div className="wh-regime-pill">
            <span>{text("macro.fomc")}</span>
            {fomc && left != null ? (
              <>
                <strong>
                  {text("macro.countdown", {
                    days: Math.max(0, Math.floor(left / 86400000)),
                    hours: Math.max(0, Math.floor((left % 86400000) / 3600000)),
                  })}
                </strong>
                <em>
                  {text("macro.meeting", {
                    meeting: fomc.meeting,
                    at: fomc.decision_at.slice(0, 16).replace("T", " "),
                  })}
                  {fomc.projections ? ` · ${text("macro.projections")}` : ""}
                </em>
              </>
            ) : (
              <strong className="wh-regime-error">
                {text("missing")}
                {data.fomc_error ? `: ${data.fomc_error}` : ""}
              </strong>
            )}
          </div>
          <div className="wh-regime-pill">
            <span>{text("macro.spread")}</span>
            {spread ? (
              <>
                <strong>
                  {`${spread.spread > 0 ? "+" : ""}${spread.spread.toFixed(2)}%`}
                </strong>
                <em>
                  {text(spread.inverted ? "macro.inverted" : "macro.normal")}
                  {" · "}
                  {text("macro.spreadDetail", {
                    ten: spread.ten_year.toFixed(2),
                    one: spread.one_year.toFixed(2),
                    day: spread.day,
                  })}
                </em>
              </>
            ) : (
              <strong className="wh-regime-error">
                {text("missing")}
                {data.spread_error ? `: ${data.spread_error}` : ""}
              </strong>
            )}
          </div>
        </div>
      )}
      <p className="wh-regime-note">{text("macro.note")}</p>
    </details>
  );
}
