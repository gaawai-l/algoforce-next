// AlphaBTC ④–⑧ cycle decision flow (client v2.95.0, read 2026-09-28). Every value here is the
// author's static table: the phase, pattern and option/risk actions are chosen by hand, not
// derived from market data. Chinese is the author's wording; English is our translation.

export type Copy = { zh: string; en: string };
export type Action = "up" | "down" | "buyback";
export type Leg = "nc" | "fc" | "np" | "fp";
export type Side = "intra" | "multi";
export type RiskRow = "up" | "cover";
export type RiskDir = "up" | "down" | "hl" | "bb";

export type Pattern = {
  id: string;
  label: Copy;
  when?: Copy;
  headline?: Copy;
  model?: Copy;
  options?: { lead?: Copy; text: Copy };
  acts?: Record<Leg, Action>;
  risk?: { text: Copy; pending?: Copy };
};

export type Phase = {
  id: string;
  name: Copy;
  state?: Copy;
  skew?: string;
  patterns: Pattern[] | null;
};

export const PHASES: Phase[] = [
  {
    id: "capitulation",
    name: { zh: "熊市投降", en: "Bear capitulation" },
    state: { zh: "恐慌割肉", en: "Panic selling" },
    skew: "Fat Left Tails",
    patterns: null,
  },
  {
    id: "breakout",
    name: { zh: "初期突破", en: "Early breakout" },
    state: { zh: "阴跌猛涨", en: "Grind down, then surge" },
    skew: "Positive Skewness",
    patterns: [
      {
        id: "decay",
        label: { zh: "突破衰减", en: "Breakout fading" },
        when: { zh: "暴涨后", en: "After a pump" },
        headline: {
          zh: "上涨突破衰减后阴跌",
          en: "Breakout fades, then grinds down",
        },
        model: {
          zh: "Demark 多周期趋势衰减模型",
          en: "DeMark multi-timeframe exhaustion model",
        },
        options: {
          text: {
            zh: "近期 put 上移,call 近期下移",
            en: "Move near puts up, near calls down",
          },
        },
        acts: { nc: "down", fc: "up", np: "up", fp: "up" },
        risk: {
          text: {
            zh: "call 近期同期上移,put 备兑",
            en: "Calls: roll near and same-tenor up; puts: cover",
          },
        },
      },
      {
        id: "grind",
        label: { zh: "阴跌突破", en: "Grind-down breakout" },
        when: { zh: "暴涨前", en: "Before a pump" },
        headline: {
          zh: "阴跌波动率挤压后暴涨",
          en: "Grind-down volatility squeeze, then pump",
        },
        model: { zh: "暴涨监测器", en: "Melt-up monitor" },
        options: {
          lead: { zh: "Call、PUT 上移", en: "Move calls and puts up" },
          text: {
            zh: "买回近期的 call,上移 / 新增卖出 2-4 周 PUT",
            en: "Buy back near calls; roll up or sell new 2–4 week puts",
          },
        },
        acts: { nc: "buyback", fc: "up", np: "up", fp: "up" },
        risk: {
          text: {
            zh: "call 突破同期上移 1 换多,put 激进备兑",
            en: "Calls: on breakout roll same-tenor up 1-for-many; puts: aggressive cover",
          },
          pending: {
            zh: "「1 换多」待确认",
            en: "“1-for-many” awaits the author",
          },
        },
      },
    ],
  },
  {
    id: "advanced",
    name: { zh: "牛市确认", en: "Bull confirmed" },
    state: { zh: "慢涨急跌", en: "Slow rise, sharp drop" },
    skew: "Negative Skewness",
    patterns: [
      { id: "exhaust", label: { zh: "跌势衰竭", en: "Downtrend exhausted" } },
      {
        id: "grindup",
        label: { zh: "跌后慢涨", en: "Slow rise after a drop" },
      },
      {
        id: "slowfast",
        label: { zh: "慢涨急跌", en: "Slow rise, sharp drop" },
      },
    ],
  },
  {
    id: "fomo",
    name: { zh: "牛市顶部", en: "Bull top" },
    skew: "FOMO",
    patterns: null,
  },
  { id: "end", name: { zh: "牛市终结", en: "Bull end" }, patterns: null },
];

export const DEFAULT_PHASE = "breakout";
export const LEGS: Leg[] = ["nc", "fc", "np", "fp"];
export const SIDES: {
  id: Side;
  anchor: "intraday" | "swing";
  rows: Leg[][];
}[] = [
  {
    id: "intra",
    anchor: "intraday",
    rows: [
      ["nc", "fc"],
      ["np", "fp"],
    ],
  },
  {
    id: "multi",
    anchor: "swing",
    rows: [
      ["nc", "fc"],
      ["np", "fp"],
    ],
  },
];
export const ACTION_CYCLE: Action[] = ["up", "down", "buyback"];
export const RISK_ROWS: RiskRow[] = ["up", "cover"];
export const RISK_DEFAULT: Record<
  RiskRow,
  Record<Leg, { sel: boolean; dir: RiskDir }>
> = {
  up: {
    nc: { sel: true, dir: "up" },
    fc: { sel: true, dir: "up" },
    np: { sel: true, dir: "up" },
    fp: { sel: true, dir: "up" },
  },
  cover: {
    nc: { sel: false, dir: "hl" },
    fc: { sel: false, dir: "hl" },
    np: { sel: true, dir: "hl" },
    fp: { sel: true, dir: "hl" },
  },
};

type Row = { tf: Copy; cells: [Copy, Copy, Copy]; na?: number[] };
const tf = {
  h1: { zh: "1 小时", en: "1h" },
  h4: { zh: "4 小时", en: "4h" },
  d1: { zh: "日线", en: "Daily" },
};
const dash = { zh: "—", en: "—" };
export const BACKTEST: Record<
  "put" | "call",
  { lead: Copy; hint: Copy; rows: Row[] }
> = {
  put: {
    lead: {
      zh: "卖 Put · Buy 13 出现后,行权价取 Risk Level",
      en: "Sell put · after a Buy 13, strike = Risk Level",
    },
    hint: { zh: "胜率 ↔ 持有期上限", en: "Win rate ↔ max holding period" },
    rows: [
      {
        tf: tf.h1,
        cells: [
          { zh: "≤ 1.5 天", en: "≤ 1.5 days" },
          { zh: "≤ 1 周", en: "≤ 1 week" },
          { zh: "≈ 53 天", en: "≈ 53 days" },
        ],
      },
      {
        tf: tf.h4,
        cells: [
          { zh: "≤ 8 天", en: "≤ 8 days" },
          { zh: "≤ 15 天", en: "≤ 15 days" },
          { zh: "≈ 71 天", en: "≈ 71 days" },
        ],
      },
      {
        tf: tf.d1,
        cells: [
          { zh: "≤ 5 周", en: "≤ 5 weeks" },
          { zh: "≤ 9 周", en: "≤ 9 weeks" },
          {
            zh: "样本仅 16 次 · 不作结论",
            en: "only 16 samples · no conclusion",
          },
        ],
        na: [2],
      },
    ],
  },
  call: {
    lead: {
      zh: "卖 Call · Sell 13 出现后,行权价取 Risk Level",
      en: "Sell call · after a Sell 13, strike = Risk Level",
    },
    hint: {
      zh: "单个 13 已是最优 · 叠加 9+13 / 双周期同向 13 均无增益",
      en: "A single 13 is best · adding 9+13 or a same-side 13 on another timeframe does not help",
    },
    rows: [
      {
        tf: tf.h1,
        cells: [
          dash,
          { zh: "≤ 1 天(75%)", en: "≤ 1 day (75%)" },
          { zh: "≈ 3.3 天", en: "≈ 3.3 days" },
        ],
        na: [0],
      },
      {
        tf: tf.h4,
        cells: [
          dash,
          { zh: "≤ 4 天(68%)", en: "≤ 4 days (68%)" },
          { zh: "≈ 7.5 天", en: "≈ 7.5 days" },
        ],
        na: [0],
      },
      {
        tf: tf.d1,
        cells: [
          dash,
          dash,
          {
            zh: "≈ 14 天 · 第 24 根仅 56%",
            en: "≈ 14 days · only 56% at bar 24",
          },
        ],
        na: [0, 1, 2],
      },
    ],
  },
};

export type FlowState = {
  phase: string;
  pattern: Record<string, string>;
  act: Record<string, Partial<Record<`${Side}:${Leg}`, Action>>>;
  actSel: Record<string, Partial<Record<`${Side}:${Leg}`, boolean>>>;
  risk: Record<
    string,
    Partial<Record<`${RiskRow}:${Leg}`, { sel: boolean; dir: RiskDir }>>
  >;
  backtest: "put" | "call";
};

export const DEFAULT_STATE: FlowState = {
  phase: DEFAULT_PHASE,
  pattern: {},
  act: {},
  actSel: {},
  risk: {},
  backtest: "put",
};

export function selectablePatterns(phase: Phase) {
  return phase.patterns ?? [];
}

export function currentPattern(state: FlowState): Pattern | null {
  const phase = PHASES.find((p) => p.id === state.phase) ?? PHASES[1];
  const patterns = selectablePatterns(phase);
  return (
    patterns.find((p) => p.id === state.pattern[phase.id]) ??
    patterns[0] ??
    null
  );
}

export function actionOf(
  state: FlowState,
  pattern: Pattern,
  side: Side,
  leg: Leg,
): Action | null {
  return (
    state.act[pattern.id]?.[`${side}:${leg}`] ?? pattern.acts?.[leg] ?? null
  );
}

export function nextAction(action: Action): Action {
  return ACTION_CYCLE[(ACTION_CYCLE.indexOf(action) + 1) % ACTION_CYCLE.length];
}

export function riskOf(
  state: FlowState,
  pattern: Pattern,
  row: RiskRow,
  leg: Leg,
) {
  return state.risk[pattern.id]?.[`${row}:${leg}`] ?? RISK_DEFAULT[row][leg];
}

export function nextRiskDir(row: RiskRow, dir: RiskDir): RiskDir {
  if (row === "cover") return dir === "hl" ? "bb" : "hl";
  return dir === "up" ? "down" : "up";
}

const STORAGE_KEY = "wh.strategy-flow.v1";

export function loadState(): FlowState {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!raw || typeof raw !== "object") return DEFAULT_STATE;
    return {
      ...DEFAULT_STATE,
      ...raw,
      phase: PHASES.some((p) => p.id === raw.phase) ? raw.phase : DEFAULT_PHASE,
      backtest: raw.backtest === "call" ? "call" : "put",
    };
  } catch {
    return DEFAULT_STATE;
  }
}

export function saveState(state: FlowState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for this visit only.
  }
}
