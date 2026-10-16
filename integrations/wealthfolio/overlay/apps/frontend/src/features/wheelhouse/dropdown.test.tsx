import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, afterAll, expect, it } from "vitest";
import { useState } from "react";
import { Dropdown, DropdownOption } from "./dropdown";

const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
beforeAll(() => {
  HTMLElement.prototype.scrollIntoView = () => {};
});
afterAll(() => {
  HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
});
afterEach(cleanup);

it("uses an in-page listbox and preserves an empty-valued latest-snapshot option", async () => {
  function Example() {
    const [value, setValue] = useState("");
    return (
      <Dropdown
        aria-label="Saved analysis"
        value={value}
        onValueChange={setValue}
      >
        <DropdownOption value="">Latest captured analysis</DropdownOption>
        <DropdownOption value="old">Historical snapshot</DropdownOption>
      </Dropdown>
    );
  }
  render(<Example />);
  const trigger = screen.getByRole("combobox", { name: "Saved analysis" });
  expect(trigger.tagName).toBe("BUTTON");
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  const option = await screen.findByRole("option", {
    name: "Historical snapshot",
  });
  fireEvent.click(option);
  await waitFor(() =>
    expect(trigger.textContent).toContain("Historical snapshot"),
  );
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(
    await screen.findByRole("option", { name: "Latest captured analysis" }),
  );
  await waitFor(() =>
    expect(trigger.textContent).toContain("Latest captured analysis"),
  );
});

it("preserves real form values, required validation and reset", async () => {
  render(
    <form aria-label="Account form">
      <label>
        Account
        <Dropdown name="account" aria-label="Account" required>
          <DropdownOption value="">Choose account…</DropdownOption>
          <DropdownOption value="demo">Demo account</DropdownOption>
        </Dropdown>
      </label>
    </form>,
  );
  const form = screen.getByRole("form", {
    name: "Account form",
  }) as HTMLFormElement;
  expect(form.checkValidity()).toBe(false);
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Account" }), {
    key: "ArrowDown",
  });
  fireEvent.click(await screen.findByRole("option", { name: "Demo account" }));
  await waitFor(() => expect(new FormData(form).get("account")).toBe("demo"));
  expect(form.checkValidity()).toBe(true);
  fireEvent.reset(form);
  await waitFor(() => expect(form.checkValidity()).toBe(false));
});

it("selects the first real option for an uncontrolled form field without a placeholder", () => {
  render(
    <form aria-label="Units form">
      <Dropdown name="kind" aria-label="Kind">
        <DropdownOption>stock</DropdownOption>
        <DropdownOption>put</DropdownOption>
      </Dropdown>
    </form>,
  );
  expect(
    new FormData(screen.getByRole("form") as HTMLFormElement).get("kind"),
  ).toBe("stock");
});
