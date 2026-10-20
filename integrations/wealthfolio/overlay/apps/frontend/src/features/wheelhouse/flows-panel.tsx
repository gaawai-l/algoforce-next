import { useSearchParams } from "react-router-dom";
import { AgeCohortChart } from "./age-cohort-chart";
import type { Stream } from "./client";
import { CostBasisHistoryChart } from "./cost-basis-history-chart";
import { CostFlowCharts } from "./cost-flow-charts";
import { useWheelhouseText } from "./i18n";
import { PerpStates } from "./perp-states";
import { SellerCharts } from "./seller-charts";
import { SellSideCharts } from "./sell-side-charts";
import { SizeCohortsCharts } from "./size-cohorts-charts";

type Flow = "seller" | "sellside" | "costbasis" | "sizes" | "perp";
const flows: Flow[] = ["seller", "sellside", "costbasis", "sizes", "perp"];
const LABELS = {
  seller: "flows.seller",
  sellside: "flows.sellside",
  costbasis: "flows.costbasis",
  sizes: "flows.sizes",
  perp: "flows.perp",
} as const;

// Five views of BTC flows, chosen with the `flow` parameter: seller pressure, the sell side, the
// buying and selling by cost basis, the wallet-size cohorts, and perp states.
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
        <>
          <CostFlowCharts />
          <CostBasisHistoryChart />
        </>
      ) : flow === "sizes" ? (
        <SizeCohortsCharts />
      ) : (
        <PerpStates />
      )}
    </div>
  );
}
