import { useSearchParams } from "react-router-dom";
import { AgeCohortChart } from "./age-cohort-chart";
import type { Stream } from "./client";
import { CostFlowCharts } from "./cost-flow-charts";
import { useWheelhouseText } from "./i18n";
import { PerpStates } from "./perp-states";
import { SellerCharts } from "./seller-charts";
import { SellSideCharts } from "./sell-side-charts";

type Flow = "seller" | "sellside" | "costbasis" | "perp";
const flows: Flow[] = ["seller", "sellside", "costbasis", "perp"];
const LABELS = {
  seller: "flows.seller",
  sellside: "flows.sellside",
  costbasis: "flows.costbasis",
  perp: "flows.perp",
} as const;

// Four views of BTC flows, chosen with the `flow` parameter: seller pressure, the sell side, the
// buying and selling by cost basis, and perp states.
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
            {text(LABELS[item])}
          </button>
        ))}
      </div>
      {flow === "seller" ? (
        <SellerCharts />
      ) : flow === "sellside" ? (
        <>
          <SellSideCharts />
          <AgeCohortChart />
        </>
      ) : flow === "costbasis" ? (
        <CostFlowCharts />
      ) : (
        <PerpStates />
      )}
    </div>
  );
}
