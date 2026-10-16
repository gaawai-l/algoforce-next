import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LevelsRail, railWidth, type RailBand } from "./levels-rail";

const band = (over: Partial<RailBand> = {}): RailBand => ({
  id: "sth-2",
  cohort: "sth",
  index: 2,
  price: 82250,
  low: 77264.5,
  high: 87235.5,
  strength: 1,
  btc: 1910000,
  share: 0.521,
  ...over,
});
// The domain is 80,000..90,000 drawn on y 18..418, so one dollar is 0.04px.
const y = (price: number) => 18 + ((90000 - price) / 10000) * 400;
const RAIL_X = 844;
const RAIL_WIDTH = 28;
const num = (node: Element, name: string) => Number(node.getAttribute(name));
const draw = (bands: RailBand[], onActive = vi.fn(), onKeyDown = vi.fn()) =>
  render(
    <svg onKeyDown={onKeyDown}>
      <LevelsRail
        bands={bands}
        y={y}
        top={90000}
        bottom={80000}
        x={RAIL_X}
        width={RAIL_WIDTH}
        plotLeft={16}
        plotRight={840}
        onActive={onActive}
      />
    </svg>,
  );

afterEach(cleanup);

describe("railWidth", () => {
  it("is 28 on a wide chart and 16 below 600px", () => {
    expect(railWidth(980)).toBe(28);
    expect(railWidth(600)).toBe(28);
    expect(railWidth(599)).toBe(16);
    expect(railWidth(500)).toBe(16);
  });
});

describe("LevelsRail", () => {
  it("lists one focusable item per band inside the price range", () => {
    draw([
      band(),
      band({ id: "lth-1", cohort: "lth", index: 1, low: 91000, high: 95000 }),
      band({ id: "lth-3", cohort: "lth", index: 3, low: 60000, high: 79000 }),
    ]);
    const list = screen.getByRole("list", { name: "Cost-basis bands" });
    const items = screen.getAllByRole("listitem");
    expect(list.contains(items[0])).toBe(true);
    expect(items).toHaveLength(1);
    expect(items[0].getAttribute("tabindex")).toBe("0");
    expect(items[0].getAttribute("aria-label")).toBe("STH K2 · $82,250");
  });

  it("clips a band that crosses the edge of the price range", () => {
    draw([band({ low: 88000, high: 95000 })]);
    const item = screen.getByRole("listitem");
    expect(num(item, "y")).toBe(y(90000));
    expect(num(item, "y") + num(item, "height")).toBe(y(88000));
  });

  it("keeps STH in the left lane and LTH in the right lane", () => {
    draw([band(), band({ id: "lth-1", cohort: "lth", index: 1 })]);
    const [sth, lth] = screen.getAllByRole("listitem");
    const half = RAIL_X + RAIL_WIDTH / 2;
    expect(num(sth, "x")).toBeGreaterThanOrEqual(RAIL_X);
    expect(num(sth, "x") + num(sth, "width")).toBeLessThanOrEqual(half);
    expect(num(lth, "x")).toBeGreaterThanOrEqual(half);
    expect(num(lth, "x") + num(lth, "width")).toBeLessThanOrEqual(
      RAIL_X + RAIL_WIDTH,
    );
  });

  it("widens a band as its strength grows", () => {
    const strengths = [0, 0.3, 0.7, 1];
    draw(
      strengths.map((strength, i) =>
        band({ id: `sth-${i + 1}`, index: i + 1, strength }),
      ),
    );
    const widths = screen
      .getAllByRole("listitem")
      .map((item) => num(item, "width"));
    // laneWidth = 28 / 2 - 1 = 13: the weakest band is 2px, the strongest fills the lane.
    expect(widths[0]).toBe(2);
    expect(widths.at(-1)).toBe(13);
    for (let i = 1; i < widths.length; i++)
      expect(widths[i]).toBeGreaterThan(widths[i - 1]);
  });

  it("spreads the focused band across the plot and reports it", () => {
    const onActive = vi.fn();
    const sth2 = band({ low: 88000, high: 95000 });
    const view = draw([sth2], onActive);
    const item = screen.getByRole("listitem");
    expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    act(() => item.focus());
    const spread = view.container.querySelector(".wh-rail-spread")!;
    expect(num(spread, "x")).toBe(16);
    expect(num(spread, "width")).toBe(840 - 16);
    expect(num(spread, "y")).toBe(num(item, "y"));
    expect(num(spread, "height")).toBe(num(item, "height"));
    expect(onActive).toHaveBeenLastCalledWith(sth2);
    act(() => item.blur());
    expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    expect(onActive).toHaveBeenLastCalledWith(null);
  });

  it("spreads the hovered band", () => {
    const onActive = vi.fn();
    const view = draw([band()], onActive);
    const item = screen.getByRole("listitem");
    fireEvent.pointerEnter(item);
    expect(view.container.querySelector(".wh-rail-spread")).not.toBeNull();
    expect(onActive).toHaveBeenLastCalledWith(band());
    fireEvent.pointerLeave(item);
    expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    expect(onActive).toHaveBeenLastCalledWith(null);
  });

  it("drops the active band when a refresh removes it or moves it out of range", () => {
    const onActive = vi.fn();
    const rail = (bands: RailBand[]) => (
      <svg>
        <LevelsRail
          bands={bands}
          y={y}
          top={90000}
          bottom={80000}
          x={RAIL_X}
          width={RAIL_WIDTH}
          plotLeft={16}
          plotRight={840}
          onActive={onActive}
        />
      </svg>
    );
    const view = render(rail([band()]));
    act(() => screen.getByRole("listitem").focus());
    expect(onActive).toHaveBeenLastCalledWith(band());
    view.rerender(rail([band({ low: 95000, high: 99000 })]));
    expect(onActive).toHaveBeenLastCalledWith(null);
    expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    // Back in range it is not active again on its own.
    view.rerender(rail([band()]));
    expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    act(() => screen.getByRole("listitem").focus());
    onActive.mockClear();
    view.rerender(rail([]));
    expect(onActive).toHaveBeenCalledWith(null);
  });

  it("keeps arrow keys on a band away from the chart", () => {
    const onKeyDown = vi.fn();
    draw([band()], vi.fn(), onKeyDown);
    fireEvent.keyDown(screen.getByRole("listitem"), { key: "ArrowLeft" });
    expect(onKeyDown).not.toHaveBeenCalled();
  });
});
