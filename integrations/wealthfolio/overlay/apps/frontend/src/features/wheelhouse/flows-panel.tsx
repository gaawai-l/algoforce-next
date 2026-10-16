import { useSearchParams } from "react-router-dom";
import type { Stream } from "./client";
import { useWheelhouseText } from "./i18n";

type Flow = "seller" | "perp";
const flows: Flow[] = ["seller", "perp"];

// P1 shell: both views are honest placeholders until their data sources exist.
export function FlowsPanel({ symbol }: { symbol: Stream["symbol"] }) {
  const { text } = useWheelhouseText();
  const [search, setSearch] = useSearchParams();
  if (symbol !== "BTCUSDT")
    return <p className="wh-flows-note">{text("flows.btcOnly")}</p>;
  const flow = flows.find((item) => item === search.get("flow")) ?? "seller";
  const setFlow = (value: Flow) =>
    setSearch(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("flow", value);
        return next;
      },
      { replace: true },
    );
  return (
    <div className="wh-flows">
      <div
        className="wh-flows-switch"
        role="group"
        aria-label={text("flows.view")}
      >
        {flows.map((item) => (
          <button
            key={item}
            aria-pressed={item === flow}
            onClick={() => setFlow(item)}
          >
            {text(item === "seller" ? "flows.seller" : "flows.perp")}
          </button>
        ))}
      </div>
      {flow === "seller" ? (
        <p className="wh-flows-note">{text("flows.sellerPending")}</p>
      ) : (
        <p className="wh-flows-note wh-flows-note--pending">
          {text("flows.perpPending")}
        </p>
      )}
    </div>
  );
}
