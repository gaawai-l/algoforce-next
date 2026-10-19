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

  it("draws nothing for a band that covers the whole price range", () => {
    draw([
      band({ id: "sth-1", index: 1, price: 82000, low: 70000, high: 95000 }),
      band({ id: "sth-2", index: 2, price: 85000, low: 80000, high: 90000 }),
      // Touching one edge of the range still tells where the band ends.
      band({ id: "sth-3", index: 3, price: 83000, low: 80000, high: 89000 }),
      band({ id: "lth-1", cohort: "lth", index: 1, low: 79000, high: 89000 }),
    ]);
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "STH K3 · $83,000",
      "LTH K1 · $82,250",
    ]);
    expect(items.map((item) => item.getAttribute("aria-setsize"))).toEqual([
      "2",
      "2",
    ]);
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
    // In list order: aria-posinset follows the K number, whatever the paint order is.
    const widths = screen
      .getAllByRole("listitem")
      .sort((a, b) => num(a, "aria-posinset") - num(b, "aria-posinset"))
      .map((item) => num(item, "width"));
    // laneWidth = 28 / 2 - 1 = 13: the weakest band is 2px, the strongest fills the lane.
    expect(widths[0]).toBe(2);
    expect(widths.at(-1)).toBe(13);
    for (let i = 1; i < widths.length; i++)
      expect(widths[i]).toBeGreaterThan(widths[i - 1]);
  });

  it("paints a lane's widest band first so every band keeps a visible strip", () => {
    const nested = [
      band({
        id: "sth-2",
        index: 2,
        price: 85000,
        low: 84000,
        high: 86000,
        strength: 0.3,
      }),
      band({
        id: "sth-3",
        index: 3,
        price: 85000,
        low: 83000,
        high: 87000,
        strength: 0.6,
      }),
      band({
        id: "sth-4",
        index: 4,
        price: 85000,
        low: 81000,
        high: 89000,
        strength: 1,
      }),
    ];
    const view = draw(nested);
    const items = screen.getAllByRole("listitem");
    // Paint order is DOM order: widest to narrowest, so a narrower band sits on top.
    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "STH K4 · $85,000",
      "STH K3 · $85,000",
      "STH K2 · $85,000",
    ]);
    const box = (node: Element) => ({
      left: num(node, "x"),
      right: num(node, "x") + num(node, "width"),
      top: num(node, "y"),
      bottom: num(node, "y") + num(node, "height"),
    });
    items.forEach((item, i) => {
      const own = box(item);
      for (const later of items.slice(i + 1)) {
        const over = box(later);
        const covered =
          over.left <= own.left &&
          over.right >= own.right &&
          over.top <= own.top &&
          over.bottom >= own.bottom;
        expect(covered).toBe(false);
      }
    });
    // The list position still follows the K number.
    expect(
      items.map((item) => [
        item.getAttribute("aria-posinset"),
        item.getAttribute("aria-setsize"),
      ]),
    ).toEqual([
      ["3", "3"],
      ["2", "3"],
      ["1", "3"],
    ]);
    expect(view.container.querySelector(".wh-rail-active")).toBeNull();
    // The active band's outline is drawn last, over every band.
    act(() => items[1].focus());
    const last = screen.getByRole("list").lastElementChild!;
    expect(last.classList.contains("wh-rail-active")).toBe(true);
    expect(last.getAttribute("aria-hidden")).toBe("true");
    expect(box(last)).toEqual(box(items[1]));
    fireEvent.pointerEnter(items[2]);
    expect(box(screen.getByRole("list").lastElementChild!)).toEqual(
      box(items[2]),
    );
  });

  it("reports no active band once it unmounts", () => {
    const onActive = vi.fn();
    const view = draw([band()], onActive);
    act(() => screen.getByRole("listitem").focus());
    expect(onActive).toHaveBeenLastCalledWith(band());
    view.unmount();
    expect(onActive).toHaveBeenLastCalledWith(null);
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
