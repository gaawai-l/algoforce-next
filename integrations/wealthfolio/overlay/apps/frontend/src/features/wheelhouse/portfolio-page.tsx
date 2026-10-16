import { Dropdown, DropdownOption } from "./dropdown";
import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Page, PageContent, PageHeader } from "@wealthfolio/ui";
import { LanguageToggle } from "./language-toggle";
import { useWheelhouseText } from "./i18n";
import {
  portfolioRequest,
  currentSync,
  portfolioWorkspace,
  displayAmount as amount,
  type Account,
  type BrokerAccount,
  type Connection,
  type LedgerEvent,
  type Source,
} from "./portfolio-client";
import { stamp } from "./client";
import "./market.css";
import "./portfolio.css";

const field = (data: FormData, name: string) => String(data.get(name) ?? "");
const nullable = (data: FormData, name: string) =>
  field(data, name).trim() || null;
function utc(value: string): string {
  const date = new Date(value.endsWith("Z") ? value : value + "Z");
  if (!Number.isFinite(date.getTime()))
    throw new Error("Enter an ISO UTC timestamp, such as 2026-09-25T20:00:00.");
  return date.toISOString();
}

export default function PortfolioPage() {
  const { text } = useWheelhouseText();
  const location = useLocation();
  const mode = location.pathname.endsWith("wheel-cycles")
    ? "cycles"
    : location.pathname.endsWith("risk-exposure")
      ? "risk"
      : "broker";
  const titles = {
    broker: text("nav.brokerage"),
    cycles: text("nav.cycles"),
    risk: text("nav.risk"),
  };
  const [query, setQuery] = useSearchParams();
  const cache = useQueryClient();
  const selectedAccount = cache.getQueryData<{
    source: Source;
    account: string;
  }>(["portfolio-selection"]);
  const source: Source =
    query.get("source") === "demo"
      ? "demo"
      : query.has("source")
        ? "moomoo"
        : (selectedAccount?.source ?? "moomoo");
  const account = query.get("account") ?? selectedAccount?.account ?? "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [discovered, setDiscovered] = useState<BrokerAccount[]>([]);
  const [cycleId, setCycleId] = useState("");
  const [fill, setFill] = useState<Record<string, unknown> | null>(null);
  const [instrumentCode, setInstrumentCode] = useState("");
  const accounts = useQuery({
    queryKey: ["portfolio", "accounts"],
    queryFn: () => portfolioRequest<Account[]>("/accounts"),
  });
  const connection = useQuery({
    queryKey: ["portfolio", "connection"],
    queryFn: () => portfolioRequest<Connection>("/connection"),
    refetchInterval: 10000,
  });
  const workspace = useQuery({
    queryKey: ["portfolio", "workspace", source, account],
    queryFn: () => portfolioWorkspace(source, account),
    enabled: !!account,
    refetchInterval: 30000,
    retry: false,
  });
  const syncStatus = useQuery({
    queryKey: ["portfolio", "sync", account],
    queryFn: () => currentSync(account),
    enabled: source === "moomoo" && /^\d+$/.test(account),
    refetchInterval: 1000,
    retry: false,
  });
  const syncActive =
    !!syncStatus.data &&
    ["queued", "running", "retry_wait"].includes(syncStatus.data.state);
  useEffect(() => {
    if (syncStatus.data?.updated_at) {
      void cache.invalidateQueries({
        queryKey: ["portfolio", "workspace", source, account],
      });
      void cache.invalidateQueries({ queryKey: ["portfolio", "accounts"] });
    }
  }, [syncStatus.data?.updated_at, source, account, cache]);
  const data = workspace.data;
  const capture = data?.capture;
  const selected =
    data?.cycles.find((item) => item.cycle.cycle_id === cycleId) ??
    data?.cycles[0];
  const options = capture?.instruments ?? [];
  const changed = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      await cache.invalidateQueries({ queryKey: ["portfolio"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const choose = (value: string) => {
    const [s, ...rest] = value.split(":");
    setQuery({ source: s, account: rest.join(":") });
    cache.setQueryData(["portfolio-selection"], {
      source: s,
      account: rest.join(":"),
    });
    setCycleId("");
    setFill(null);
  };
  const demo = () =>
    changed(async () => {
      await portfolioRequest("/demo", {});
      setQuery({ source: "demo", account: "wheelhouse-demo" });
      cache.setQueryData(["portfolio-selection"], {
        source: "demo",
        account: "wheelhouse-demo",
      });
      setMessage("Fictional account loaded in its own demo namespace.");
    });
  const discover = () =>
    changed(async () => {
      const items = await portfolioRequest<BrokerAccount[]>("/discover", {});
      setDiscovered(items);
      setMessage(
        items.length
          ? "Select the account explicitly before syncing."
          : "No REAL FUTUSG accounts were returned.",
      );
    });
  const sync = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void changed(async () => {
      const id = field(form, "account");
      await portfolioRequest("/sync", {
        account_id: id,
        start: field(form, "start"),
        end: field(form, "end"),
      });
      setQuery({ source: "moomoo", account: id });
      cache.setQueryData(["portfolio-selection"], {
        source: "moomoo",
        account: id,
      });
      setMessage(
        "Read-only sync queued. Snapshots are saved first; order fees continue in paced batches.",
      );
    });
  };
  const addCycle = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void changed(async () => {
      const result = await portfolioRequest<{ cycle_id: string }>("/cycles", {
        source,
        account_id: account,
        name: field(form, "name"),
        underlying: field(form, "underlying"),
        currency: field(form, "currency"),
      });
      setCycleId(result.cycle_id);
      setMessage(
        "Cycle created. Assign executions or explicit lifecycle records below.",
      );
    });
  };
  const addEvent = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void changed(async () => {
      const instrument = options.find(
        (item) => item.code === field(form, "instrument"),
      );
      if (!instrument || !selected)
        throw new Error(
          "Select a cycle and register verified instrument metadata first.",
        );
      const request: LedgerEvent = {
        event_id: crypto.randomUUID(),
        cycle_id: selected.cycle.cycle_id,
        at: utc(field(form, "at")),
        kind: field(form, "kind") as LedgerEvent["kind"],
        instrument,
        quantity: field(form, "quantity"),
        price: field(form, "price"),
        fee: nullable(form, "fee"),
        source_record_id: fill ? String(fill.record_id) : null,
        settlement_record_id: nullable(form, "delivery"),
        roll_group: nullable(form, "roll"),
        author: field(form, "author"),
        reason: field(form, "reason"),
      };
      await portfolioRequest("/events", request);
      setFill(null);
      setMessage("Analytical ledger event recorded. No trade was sent.");
    });
  };
  const annotation = (
    event: FormEvent<HTMLFormElement>,
    kind: "instrument" | "quote" | "fx",
  ) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void changed(async () => {
      let value: unknown;
      if (kind === "instrument") {
        const type = field(form, "kind");
        value = {
          code: field(form, "code"),
          underlying: field(form, "underlying"),
          kind: type,
          currency: field(form, "currency"),
          multiplier: field(form, "multiplier"),
          strike: type === "stock" ? null : field(form, "strike"),
          expiry: type === "stock" ? null : field(form, "expiry"),
          source: field(form, "provenance"),
        };
      } else if (kind === "quote")
        value = {
          code: field(form, "code"),
          spot: field(form, "spot"),
          delta: nullable(form, "delta"),
          gamma: nullable(form, "gamma"),
          theta: nullable(form, "theta"),
          vega: nullable(form, "vega"),
          units: field(form, "units"),
          theta_basis: field(form, "theta_basis"),
          vega_basis: field(form, "vega_basis"),
          observed_at: utc(field(form, "at")),
          source: field(form, "provenance"),
        };
      else
        value = {
          currency: field(form, "currency"),
          to_base: field(form, "rate"),
          observed_at: utc(field(form, "at")),
          source: field(form, "provenance"),
        };
      await portfolioRequest("/annotations", {
        source,
        account_id: account,
        author: field(form, "author"),
        reason: field(form, "reason"),
        [kind]: value,
      });
      setMessage(
        "Local annotation saved with provenance; broker records are preserved.",
      );
    });
  };
  const pendingFill = fill?.payload as Record<string, unknown> | undefined;
  return (
    <Page>
      <PageHeader
        heading={titles[mode]}
        text={text("portfolio.subtitle")}
        actions={<LanguageToggle />}
      />
      <PageContent>
        <div className="wh-market wh-portfolio">
          <div className="wh-toolbar">
            <label>
              Stored account
              <Dropdown
                aria-label="Stored account"
                value={account ? `${source}:${account}` : ""}
                onValueChange={(value) => choose(value)}
              >
                <DropdownOption value="" disabled>
                  Select an account…
                </DropdownOption>
                {accounts.data?.map((item) => (
                  <DropdownOption
                    key={`${item.source}:${item.account}`}
                    value={`${item.source}:${item.account}`}
                  >
                    {item.source === "demo" ? "DEMO · " : "moomoo SG · "}
                    {item.account}
                  </DropdownOption>
                ))}
              </Dropdown>
            </label>
            <button disabled={busy} onClick={() => void demo()}>
              Load fictional demo
            </button>
            <span className={`wh-badge ${source === "demo" ? "wh-amber" : ""}`}>
              {source === "demo"
                ? "SIMULATED / HISTORICAL"
                : account
                  ? "REAL ACCOUNT / READ-ONLY"
                  : "NO ACCOUNT SELECTED"}
            </span>
          </div>
          {capture && (
            <p className="wh-muted">
              Snapshot{" "}
              {stamp(capture.snapshot_observed_at ?? capture.captured_at)} ·
              Latest acquisition {stamp(capture.captured_at)} ·{" "}
              {capture.base_currency} base · {data?.state}.{" "}
              {source === "demo"
                ? "Risk evaluated at fixture time; no real account is connected."
                : "Missing data stays unavailable. A successful capture does not establish complete account history."}
            </p>
          )}
          {(error || workspace.isError) && (
            <div role="alert" className="wh-alert">
              {error || workspace.error?.message}
            </div>
          )}
          {message && (
            <p role="status" className="wh-feedback">
              {message}
            </p>
          )}
          {source === "moomoo" && syncStatus.data && (
            <div className="wh-task" role="status">
              <span>
                Account sync: {syncStatus.data.state.replaceAll("_", " ")} ·{" "}
                {syncStatus.data.phase}
              </span>
              <span>
                Fees {syncStatus.data.completed_orders}/
                {syncStatus.data.total_orders} orders · missing{" "}
                {syncStatus.data.missing_orders}
              </span>
              {syncStatus.data.error && (
                <span>{syncStatus.data.error}; saved data is preserved</span>
              )}
              {syncActive && (
                <span>Next check {stamp(syncStatus.data.next_due)}</span>
              )}
            </div>
          )}
          {mode === "broker" && (
            <>
              <section className="wh-broker-connect">
                <div className="wh-section-title">
                  <h2>moomoo Singapore connection</h2>
                  <span className="wh-badge">
                    {connection.data?.gateway_reachable
                      ? "GATEWAY REACHABLE"
                      : "OPEND OFFLINE"}
                  </span>
                </div>
                <p>{connection.data?.message ?? "Checking local gateway…"}</p>
                <p className="wh-muted">
                  Official OpenD → 127.0.0.1:11111 · FUTUSG · REAL. Sign in
                  through official OpenD on this computer. This app never asks
                  for a password or unlocks trading.
                </p>
                <button disabled={busy} onClick={() => void discover()}>
                  Discover read-only accounts
                </button>
                {discovered.length > 0 && (
                  <form onSubmit={sync} className="wh-form">
                    <label>
                      Actual account
                      <Dropdown
                        aria-label="Broker account"
                        name="account"
                        required
                      >
                        <DropdownOption value="">Choose acc_id…</DropdownOption>
                        {discovered.map((item) => (
                          <DropdownOption
                            key={item.account_id}
                            value={item.account_id}
                          >
                            {item.account_id} · {item.status} ·{" "}
                            {item.markets.join(", ")}
                          </DropdownOption>
                        ))}
                      </Dropdown>
                    </label>
                    <label>
                      History start
                      <input name="start" type="date" required />
                    </label>
                    <label>
                      History end
                      <input
                        name="end"
                        type="date"
                        required
                        max={new Date().toISOString().slice(0, 10)}
                      />
                    </label>
                    <button disabled={busy || syncActive}>
                      {syncActive
                        ? "Sync in progress…"
                        : "Sync selected account"}
                    </button>
                    <p className="wh-muted wh-wide">
                      Up to 90 days per request. Earlier availability must be
                      checked separately, including disabled accounts. Cash
                      flows use the requested creation-date range; clearing
                      dates are retained separately.
                    </p>
                  </form>
                )}
              </section>
              {capture && (
                <>
                  <h2>Broker position snapshot</h2>
                  <div className="wh-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Instrument</th>
                          <th>Signed quantity</th>
                          <th>Mark</th>
                          <th>Metadata</th>
                        </tr>
                      </thead>
                      <tbody>
                        {capture.positions.map((p) => (
                          <tr key={p.code}>
                            <td>{p.code}</td>
                            <td>{p.quantity}</td>
                            <td>{amount(p.mark)}</td>
                            <td>
                              {options.some((i) => i.code === p.code)
                                ? "Registered"
                                : "Unresolved — register below"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <details className="wh-disclosure">
                    <summary>Cash snapshot / raw broker fields</summary>
                    <pre className="wh-json">
                      {JSON.stringify(capture.raw.cash ?? [], null, 2)}
                    </pre>
                  </details>
                  <details className="wh-disclosure">
                    <summary>
                      Separate orders, executions, fees and cash flows ·{" "}
                      {data?.records.length} records
                    </summary>
                    <p className="wh-muted">
                      Orders are not fills. Fee rows are not automatically
                      allocated twice. Execution timestamps retain the broker's
                      raw representation.
                    </p>
                    <div className="wh-table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Type</th>
                            <th>Broker ID</th>
                            <th>Original record</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data?.records.map((r, i) => (
                            <tr key={i}>
                              <td>{String(r.kind)}</td>
                              <td>{String(r.broker_id)}</td>
                              <td>
                                <details>
                                  <summary>Inspect</summary>
                                  <pre className="wh-json">
                                    {JSON.stringify(r.payload, null, 2)}
                                  </pre>
                                </details>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </>
              )}
            </>
          )}
          {mode === "cycles" && capture && (
            <>
              <div className="wh-section-title">
                <h2>Explicit strategy cycles</h2>
                <span className="wh-muted">
                  FIFO · option premium realized separately
                </span>
              </div>
              <form className="wh-form" onSubmit={addCycle}>
                <label>
                  Cycle name
                  <input
                    name="name"
                    required
                    placeholder="AAPL · September Wheel"
                  />
                </label>
                <label>
                  Underlying code
                  <input name="underlying" required placeholder="US.AAPL" />
                </label>
                <label>
                  Currency
                  <input
                    name="currency"
                    required
                    pattern="[A-Z]{3}"
                    defaultValue="USD"
                  />
                </label>
                <button disabled={busy}>Create cycle</button>
              </form>
              {data?.cycles.length ? (
                <label>
                  Cycle
                  <Dropdown
                    aria-label="Cycle"
                    value={selected?.cycle.cycle_id ?? ""}
                    onValueChange={(value) => {
                      setCycleId(value);
                      setFill(null);
                    }}
                  >
                    {data.cycles.map((item) => (
                      <DropdownOption
                        key={item.cycle.cycle_id}
                        value={item.cycle.cycle_id}
                      >
                        {item.cycle.name} · {item.state}
                      </DropdownOption>
                    ))}
                  </Dropdown>
                </label>
              ) : (
                <p className="wh-empty">
                  Create a cycle to explicitly associate executions and
                  lifecycle events.
                </p>
              )}
              {selected && (
                <>
                  <div className="wh-metrics">
                    {[
                      ["Premium received", selected.premium_received],
                      ["Premium paid", selected.premium_paid],
                      ["Realized P&L · net", selected.realized_net],
                      ["Unrealized P&L", selected.unrealized],
                      ["Net cash movement", selected.net_cash_movement],
                      ["Known fees", selected.known_fees],
                    ].map(([name, value]) => (
                      <div key={name}>
                        <span>{name}</span>
                        <strong>
                          {amount(value)}{" "}
                          <small>{selected.cycle.currency}</small>
                        </strong>
                      </div>
                    ))}
                  </div>
                  <p className="wh-muted">
                    {selected.method}. Opening fees are allocated to realized
                    P&L as lots close. Unrealized values exclude unallocated
                    opening fees. This is an analytical accounting policy, not a
                    tax basis report.
                  </p>
                  {selected.issues.map((issue) => (
                    <p className="wh-warning" key={issue}>
                      {issue}
                    </p>
                  ))}
                  <h3>Open lots</h3>
                  <div className="wh-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Instrument</th>
                          <th>Signed quantity</th>
                          <th>Entry</th>
                          <th>Opening event</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.lots.map((lot, i) => (
                          <tr key={i}>
                            <td>{lot.code}</td>
                            <td>{lot.quantity}</td>
                            <td>{amount(lot.entry_price)}</td>
                            <td>{lot.opening_event_id}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <h3>Lifecycle timeline</h3>
                  <div className="wh-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>UTC time</th>
                          <th>Event</th>
                          <th>Instrument</th>
                          <th>Quantity</th>
                          <th>Price</th>
                          <th>Fee</th>
                          <th>Roll group</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.events.map((e) => (
                          <tr key={e.event_id}>
                            <td>{stamp(e.at)}</td>
                            <td>{e.kind}</td>
                            <td>{e.instrument.code}</td>
                            <td>{e.quantity}</td>
                            <td>{e.price}</td>
                            <td>{e.fee ?? "Unknown"}</td>
                            <td>{e.roll_group ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <details className="wh-disclosure">
                    <summary>Reconcile a revised broker fill</summary>
                    <p className="wh-muted">
                      Revised fills block P&amp;L until reviewed. Select the
                      original event and latest broker record, then confirm UTC
                      time and fees. Previous classifications stay in the audit
                      history.
                    </p>
                    <form
                      className="wh-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const form = new FormData(event.currentTarget);
                        void changed(async () => {
                          await portfolioRequest("/reconcile-fill", {
                            event_id: field(form, "event"),
                            record_id: field(form, "record"),
                            at: utc(field(form, "at")),
                            fee: nullable(form, "fee"),
                            author: field(form, "author"),
                            reason: field(form, "reason"),
                          });
                          setMessage(
                            "Revised fill reconciled with an audit trail.",
                          );
                        });
                      }}
                    >
                      <label>
                        Original event
                        <Dropdown
                          aria-label="Linked event"
                          name="event"
                          required
                        >
                          <DropdownOption value="">
                            Choose linked event…
                          </DropdownOption>
                          {selected.events
                            .filter(
                              (e) =>
                                e.source_record_id || e.settlement_record_id,
                            )
                            .map((e) => (
                              <DropdownOption
                                key={e.event_id}
                                value={e.event_id}
                              >
                                {e.kind} · {e.instrument.code} · {e.event_id}
                              </DropdownOption>
                            ))}
                        </Dropdown>
                      </label>
                      <label>
                        Latest broker execution
                        <Dropdown
                          aria-label="Latest record"
                          name="record"
                          required
                        >
                          <DropdownOption value="">
                            Choose latest record…
                          </DropdownOption>
                          {data?.records
                            .filter((r) => r.kind === "deals")
                            .map((r) => (
                              <DropdownOption
                                key={String(r.record_id)}
                                value={String(r.record_id)}
                              >
                                {String(r.broker_id)} ·{" "}
                                {String(
                                  (r.payload as Record<string, unknown>).code,
                                )}
                              </DropdownOption>
                            ))}
                        </Dropdown>
                      </label>
                      <label>
                        Confirmed UTC event time
                        <input
                          name="at"
                          required
                          placeholder="2026-09-25T20:00:00"
                        />
                      </label>
                      <label>
                        Confirmed fee · blank if unknown
                        <input name="fee" type="number" min="0" step="any" />
                      </label>
                      <label>
                        Author
                        <input
                          name="author"
                          required
                          defaultValue="Local user"
                        />
                      </label>
                      <label className="wh-wide">
                        Evidence / reason
                        <input name="reason" required />
                      </label>
                      <button disabled={busy}>
                        Reconcile local classification
                      </button>
                    </form>
                  </details>
                  <details className="wh-disclosure">
                    <summary>Resolve or correct an event fee</summary>
                    <p className="wh-muted">
                      This adds an audited fee overlay. Original event evidence
                      stays intact.
                    </p>
                    <form
                      className="wh-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const form = new FormData(event.currentTarget);
                        void changed(async () => {
                          await portfolioRequest("/fee-corrections", {
                            event_id: field(form, "event"),
                            fee: field(form, "fee"),
                            author: field(form, "author"),
                            reason: field(form, "reason"),
                          });
                          setMessage(
                            "Fee correction saved with an audit trail.",
                          );
                        });
                      }}
                    >
                      <label>
                        Event
                        <Dropdown
                          aria-label="Event to remove"
                          name="event"
                          required
                        >
                          {selected.events.map((e) => (
                            <DropdownOption key={e.event_id} value={e.event_id}>
                              {e.kind} · {e.instrument.code} · {stamp(e.at)}
                            </DropdownOption>
                          ))}
                        </Dropdown>
                      </label>
                      <label>
                        Confirmed fee
                        <input
                          name="fee"
                          required
                          type="number"
                          min="0"
                          step="any"
                        />
                      </label>
                      <label>
                        Author
                        <input
                          name="author"
                          required
                          defaultValue="Local user"
                        />
                      </label>
                      <label className="wh-wide">
                        Evidence
                        <input name="reason" required />
                      </label>
                      <button disabled={busy}>Save fee correction</button>
                    </form>
                  </details>
                  <details className="wh-disclosure">
                    <summary>
                      Record an analytical event or classify a fill
                    </summary>
                    <p className="wh-muted">
                      Assignment/exercise closes the option at zero premium and
                      records shares at strike. Do not also record the same
                      share delivery as another trade. Rolls are two events
                      sharing a roll group; original history remains intact.
                      Cash settlement uses a per-share cash value and does not
                      deliver stock. Same-time events follow the order you save
                      them.
                    </p>
                    {data?.records
                      .filter((r) => r.kind === "deals")
                      .map((r) => (
                        <button
                          className="wh-fill"
                          key={String(r.record_id)}
                          onClick={() => {
                            setFill(r);
                            setInstrumentCode(
                              String(
                                (r.payload as Record<string, unknown>).code ??
                                  "",
                              ),
                            );
                          }}
                        >
                          Classify fill {String(r.broker_id)}
                        </button>
                      ))}
                    {fill && (
                      <>
                        <pre className="wh-json">
                          {JSON.stringify(fill.payload, null, 2)}
                        </pre>
                        <button onClick={() => setFill(null)}>
                          Use explicit manual record
                        </button>
                      </>
                    )}
                    <form
                      key={String(fill?.record_id ?? "manual")}
                      className="wh-form"
                      onSubmit={addEvent}
                    >
                      <label>
                        Instrument
                        <Dropdown
                          aria-label="Instrument"
                          name="instrument"
                          required
                          value={instrumentCode}
                          onValueChange={(value) => setInstrumentCode(value)}
                        >
                          <DropdownOption value="">
                            Choose verified metadata…
                          </DropdownOption>
                          {options
                            .filter(
                              (i) => i.underlying === selected.cycle.underlying,
                            )
                            .map((i) => (
                              <DropdownOption key={i.code} value={i.code}>
                                {i.code} · ×{i.multiplier}
                              </DropdownOption>
                            ))}
                        </Dropdown>
                      </label>
                      <label>
                        Event
                        <Dropdown aria-label="Event kind" name="kind" required>
                          {[
                            "buy_open",
                            "sell_open",
                            "buy_close",
                            "sell_close",
                            "expire",
                            "assign",
                            "exercise",
                            "cash_settle",
                          ].map((kind) => (
                            <DropdownOption key={kind}>{kind}</DropdownOption>
                          ))}
                        </Dropdown>
                      </label>
                      <label>
                        Quantity
                        <input
                          name="quantity"
                          required
                          type="number"
                          min="0.000001"
                          step="any"
                          defaultValue={
                            pendingFill ? String(pendingFill.qty) : "1"
                          }
                        />
                      </label>
                      <label>
                        Price / share
                        <input
                          name="price"
                          required
                          type="number"
                          min="0"
                          step="any"
                          defaultValue={
                            pendingFill ? String(pendingFill.price) : "0"
                          }
                        />
                      </label>
                      <label>
                        Fee · blank if unknown
                        <input name="fee" type="number" min="0" step="any" />
                      </label>
                      <label>
                        Event time · UTC
                        <input
                          name="at"
                          required
                          placeholder="2026-09-25T20:00:00"
                        />
                      </label>
                      <label>
                        Roll group · optional
                        <input name="roll" />
                      </label>
                      <label>
                        Delivery fill record ID · assignment/exercise
                        <input
                          name="delivery"
                          placeholder="Optional underlying fill link"
                        />
                      </label>
                      <label>
                        Author
                        <input
                          name="author"
                          required
                          defaultValue="Local user"
                        />
                      </label>
                      <label className="wh-wide">
                        Evidence / reason
                        <input
                          name="reason"
                          required
                          placeholder="Statement reference, assignment record, or reconciliation note"
                        />
                      </label>
                      <button disabled={busy}>Save local ledger event</button>
                    </form>
                  </details>
                </>
              )}
            </>
          )}
          {mode === "risk" && capture && (
            <>
              <div className="wh-section-title">
                <h2>Per-underlying exposure</h2>
                <span className="wh-badge">
                  {data?.risk?.state.toUpperCase() ?? "UNAVAILABLE"}
                </span>
              </div>
              <div className="wh-metrics">
                {[
                  ["Portfolio dollar Delta", data?.risk?.dollar_delta],
                  ["Theta / calendar day", data?.risk?.theta_daily],
                  ["Vega / volatility point", data?.risk?.vega_point],
                ].map(([name, value]) => (
                  <div key={name}>
                    <span>{name}</span>
                    <strong>
                      {amount(value)} <small>{capture.base_currency}</small>
                    </strong>
                  </div>
                ))}
              </div>
              <p className="wh-muted">
                Theta is sensitivity, not guaranteed income. Portfolio dollar
                Delta includes spot and FX. Share-equivalent Delta and Gamma are
                only aggregated per underlying. Quotes and positions older than
                15 minutes are unavailable for current risk.
              </p>
              <div className="wh-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Currency</th>
                      <th>Share Delta</th>
                      <th>Share Gamma</th>
                      <th>Theta/day</th>
                      <th>Vega/point</th>
                      <th>Dollar Delta · base</th>
                      <th>Data issues</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data?.risk?.exposures.map((e) => (
                      <tr key={e.underlying + e.currency}>
                        <td>{e.underlying}</td>
                        <td>{e.currency}</td>
                        <td>{amount(e.share_delta)}</td>
                        <td>{amount(e.share_gamma)}</td>
                        <td>{amount(e.theta_daily)}</td>
                        <td>{amount(e.vega_point)}</td>
                        <td>{amount(e.dollar_delta_base)}</td>
                        <td>{e.issues.join(" · ") || "Complete"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {data?.risk?.issues.map((issue) => (
                <p className="wh-warning" key={issue}>
                  {issue}
                </p>
              ))}
            </>
          )}
          {capture && (
            <>
              <details className="wh-disclosure">
                <summary>Verified instrument metadata</summary>
                <p className="wh-muted">
                  Actual contract multiplier and identity must come from
                  broker/reference data. No default of 100 is assumed for real
                  options. Annotations are audited and preserve the original
                  snapshot.
                </p>
                <form
                  className="wh-form"
                  onSubmit={(e) => annotation(e, "instrument")}
                >
                  <label>
                    Broker code
                    <input name="code" required />
                  </label>
                  <label>
                    Underlying code
                    <input name="underlying" required />
                  </label>
                  <label>
                    Asset type
                    <Dropdown aria-label="Instrument kind" name="kind">
                      <DropdownOption>stock</DropdownOption>
                      <DropdownOption>put</DropdownOption>
                      <DropdownOption>call</DropdownOption>
                    </Dropdown>
                  </label>
                  <label>
                    Currency
                    <input
                      name="currency"
                      defaultValue="USD"
                      required
                      pattern="[A-Z]{3}"
                    />
                  </label>
                  <label>
                    Actual multiplier
                    <input
                      name="multiplier"
                      required
                      type="number"
                      min="0.000001"
                      step="any"
                    />
                  </label>
                  <label>
                    Option strike
                    <input name="strike" type="number" min="0" step="any" />
                  </label>
                  <label>
                    Option expiry
                    <input name="expiry" type="date" />
                  </label>
                  <label>
                    Metadata source
                    <input name="provenance" required />
                  </label>
                  <label>
                    Author
                    <input name="author" required defaultValue="Local user" />
                  </label>
                  <label className="wh-wide">
                    Verification note
                    <input name="reason" required />
                  </label>
                  <button disabled={busy}>Save metadata</button>
                </form>
              </details>
              {mode === "risk" && (
                <>
                  <details className="wh-disclosure">
                    <summary>Enter a sourced Greek observation</summary>
                    <p className="wh-muted">
                      Enter long-option quoted Greeks with their source units.
                      Signed position quantity is applied automatically. These
                      are manual observations, not live broker quotes.
                    </p>
                    <form
                      className="wh-form"
                      onSubmit={(e) => annotation(e, "quote")}
                    >
                      <label>
                        Instrument
                        <Dropdown
                          aria-label="Greeks instrument"
                          name="code"
                          required
                        >
                          {options.map((i) => (
                            <DropdownOption key={i.code}>
                              {i.code}
                            </DropdownOption>
                          ))}
                        </Dropdown>
                      </label>
                      <label>
                        Underlying spot
                        <input
                          name="spot"
                          required
                          type="number"
                          min="0.000001"
                          step="any"
                        />
                      </label>
                      {["delta", "gamma", "theta", "vega"].map((name) => (
                        <label key={name}>
                          {name}
                          <input name={name} type="number" step="any" />
                        </label>
                      ))}
                      <label>
                        Greek units
                        <Dropdown aria-label="Greeks units" name="units">
                          <DropdownOption value="per_share">
                            Per underlying share
                          </DropdownOption>
                          <DropdownOption value="per_contract">
                            Per contract
                          </DropdownOption>
                        </Dropdown>
                      </label>
                      <label>
                        Theta time basis
                        <Dropdown aria-label="Theta basis" name="theta_basis">
                          <DropdownOption value="day">
                            Per calendar day
                          </DropdownOption>
                          <DropdownOption value="year">
                            Per year (÷365)
                          </DropdownOption>
                        </Dropdown>
                      </label>
                      <label>
                        Vega basis
                        <Dropdown aria-label="Vega basis" name="vega_basis">
                          <DropdownOption value="percentage_point">
                            Per 1 volatility point
                          </DropdownOption>
                          <DropdownOption value="unit_volatility">
                            Per 1.0 volatility (÷100)
                          </DropdownOption>
                        </Dropdown>
                      </label>
                      <label>
                        Observed at · UTC
                        <input
                          name="at"
                          required
                          placeholder="2026-09-27T00:00:00"
                        />
                      </label>
                      <label>
                        Quote source
                        <input name="provenance" required />
                      </label>
                      <label>
                        Author
                        <input
                          name="author"
                          required
                          defaultValue="Local user"
                        />
                      </label>
                      <label>
                        Verification note
                        <input name="reason" required />
                      </label>
                      <button disabled={busy}>Save observation</button>
                    </form>
                  </details>
                  <details className="wh-disclosure">
                    <summary>Enter a sourced FX observation</summary>
                    <form
                      className="wh-form"
                      onSubmit={(e) => annotation(e, "fx")}
                    >
                      <label>
                        From currency
                        <input name="currency" required pattern="[A-Z]{3}" />
                      </label>
                      <label>
                        {capture.base_currency} per 1 foreign unit
                        <input
                          name="rate"
                          required
                          type="number"
                          min="0.000001"
                          step="any"
                        />
                      </label>
                      <label>
                        Observed at · UTC
                        <input name="at" required />
                      </label>
                      <label>
                        Source
                        <input name="provenance" required />
                      </label>
                      <label>
                        Author
                        <input
                          name="author"
                          required
                          defaultValue="Local user"
                        />
                      </label>
                      <label>
                        Note
                        <input name="reason" required />
                      </label>
                      <button disabled={busy}>Save FX observation</button>
                    </form>
                  </details>
                </>
              )}
              <details className="wh-disclosure">
                <summary>Coverage & reconciliation limitations</summary>
                {data?.issues.map((issue, i) => (
                  <p key={i} className="wh-warning">
                    {issue}
                  </p>
                ))}
                <p className="wh-muted">
                  Unclassified executions are not included in cycle P&L. Cash
                  flows, orders and fees remain separate records. Complete
                  historical account reconciliation is required before treating
                  cycle totals as total account returns.
                </p>
              </details>
              <details className="wh-disclosure">
                <summary>Local audit history</summary>
                <div className="wh-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>UTC time</th>
                        <th>Action</th>
                        <th>Author</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data?.audit.map((item, i) => (
                        <tr key={i}>
                          <td>{stamp(String(item.at))}</td>
                          <td>{String(item.action)}</td>
                          <td>{String(item.author)}</td>
                          <td>{String(item.reason)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
          {!capture && mode !== "broker" && (
            <p className="wh-empty">
              Choose an imported account or explicitly load the fictional demo.
              Real holdings are never inferred from this demonstration.
            </p>
          )}
          <footer className="wh-footer">
            No orders · No trade unlock · Local data only · Financial values are
            analytics, not execution instructions
          </footer>
        </div>
      </PageContent>
    </Page>
  );
}
