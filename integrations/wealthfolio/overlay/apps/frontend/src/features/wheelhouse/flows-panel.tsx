import { useSearchParams } from "react-router-dom";
import type { Stream } from "./client";
import { useWheelhouseText } from "./i18n";
import { SellerCharts } from "./seller-charts";

type Flow = "seller" | "perp";
const flows: Flow[] = ["seller", "perp"];

// Seller pressure is live; the perp view stays an honest placeholder until its data source exists.
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
        <SellerCharts />
      ) : (
        <p className="wh-flows-note wh-flows-note--pending">
          {text("flows.perpPending")}
        </p>
      )}
    </div>
  );
}
