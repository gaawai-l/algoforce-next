import { useState } from "react";
import { usd } from "./client";
import { useWheelhouseText, type TextFn } from "./i18n";

// One cost-basis peak drawn on the price rail, from `low` to `high` around its `price`.
export interface RailBand {
  id: string; // "sth-1"
  cohort: "sth" | "lth";
  index: number; // K number, 1-based
  price: number;
  low: number; // price - width / 2
  high: number; // price + width / 2
  strength: number; // 0..1
  btc: number;
  share: number;
}

interface RailProps {
  bands: RailBand[];
  y: (price: number) => number;
  top: number;
  bottom: number;
  x: number;
  width: number;
  plotLeft: number;
  plotRight: number;
  onActive: (band: RailBand | null) => void;
}

// The rail follows the chart's own width, not the viewport.
export const railWidth = (chartWidth: number) => (chartWidth < 600 ? 16 : 28);

const bandName = (band: RailBand) =>
  `${band.cohort.toUpperCase()} K${band.index}`;

const btcAmount = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumSignificantDigits: 3,
});

export const bandReadout = (text: TextFn, band: RailBand) =>
  text("rail.readout", {
    band: bandName(band),
    price: usd(band.price),
    width: usd(band.high - band.low),
    btc: btcAmount.format(band.btc),
    share: `${(band.share * 100).toFixed(1)}%`,
    strength: `${Math.round(band.strength * 100)}%`,
  });

export function LevelsRail({
  bands,
  y,
  top,
  bottom,
  x,
  width,
  plotLeft,
  plotRight,
  onActive,
}: RailProps) {
  const { text } = useWheelhouseText();
  const [active, setActive] = useState<string | null>(null);
  const activate = (band: RailBand | null) => {
    setActive(band?.id ?? null);
    onActive(band);
  };
  const laneWidth = width / 2 - 1;
  // Only the part inside the price range is drawn; the rail never widens the y-axis.
  const drawn = bands
    .filter((band) => band.high > bottom && band.low < top)
    .map((band) => {
      const y1 = y(Math.min(band.high, top));
      return { band, y: y1, height: y(Math.max(band.low, bottom)) - y1 };
    });
  const spread = drawn.find((d) => d.band.id === active);
  return (
    <g role="list" aria-label={text("rail.list")}>
      {spread && (
        <rect
          className={`wh-rail-spread is-${spread.band.cohort}`}
          aria-hidden="true"
          x={plotLeft}
          width={plotRight - plotLeft}
          y={spread.y}
          height={spread.height}
        />
      )}
      <rect
        className="wh-rail-track"
        aria-hidden="true"
        x={x}
        width={width}
        y={y(top)}
        height={y(bottom) - y(top)}
      />
      {drawn.map(({ band, y: bandY, height }) => (
        <rect
          key={band.id}
          className={`wh-rail-band is-${band.cohort}`}
          role="listitem"
          tabIndex={0}
          aria-label={`${bandName(band)} · ${usd(band.price)}`}
          x={x + 1 + (band.cohort === "lth" ? width / 2 : 0)}
          width={2 + band.strength * (laneWidth - 2)}
          y={bandY}
          height={height}
          onPointerEnter={() => activate(band)}
          onPointerLeave={() => activate(null)}
          onFocus={() => activate(band)}
          onBlur={() => activate(null)}
          // Arrow keys on a band must not move the chart's selected bar.
          onKeyDown={(event) => event.stopPropagation()}
        />
      ))}
    </g>
  );
}
