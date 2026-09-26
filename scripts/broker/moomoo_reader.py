"""Isolated official SDK reader. Input/output is local JSON; SDK diagnostics are suppressed."""

import contextlib
import io
import json
import sys

# The parent captures only this protocol response. SDK diagnostics never reach application logs.
result = {"ok": False, "code": "sdk_failure"}
try:
    request = json.loads(sys.stdin.read())
    if request.get("operation") not in {"accounts", "sync"}:
        raise ValueError("unsupported_operation")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import logging

        logging.disable(logging.CRITICAL)
        import moomoo as m

        m.SysConfig.set_all_thread_daemon(True)
        m.SysConfig.enable_console_log(False)
        # Prevent SDK file logs from persisting account or provider error text.
        ctx = m.OpenSecTradeContext(
            filter_trdmarket=m.TrdMarket.NONE,
            host="127.0.0.1",
            port=11111,
            security_firm=m.SecurityFirm.FUTUSG,
        )
        try:
            ret, table = ctx.get_acc_list()
            if ret != m.RET_OK:
                raise RuntimeError("account_query_failed")
            accounts = json.loads(table.to_json(orient="records"))
            accounts = [
                a
                for a in accounts
                if a.get("trd_env") == "REAL" and a.get("security_firm") == "FUTUSG"
            ]
            if request["operation"] == "accounts":
                result = {
                    "ok": True,
                    "accounts": [
                        {
                            "account_id": str(a["acc_id"]),
                            "status": a["acc_status"],
                            "markets": a["trdmarket_auth"],
                            "firm": "FUTUSG",
                            "environment": "REAL",
                        }
                        for a in accounts
                    ],
                }
            else:
                acc_id = str(request["account_id"])
                if acc_id not in {str(a["acc_id"]) for a in accounts}:
                    raise RuntimeError("account_not_authorized")
                args = {"acc_id": int(acc_id), "trd_env": m.TrdEnv.REAL}
                captures, errors = {}, {}
                queries = {
                    "positions": lambda: ctx.position_list_query(**args, refresh_cache=True),
                    "cash": lambda: ctx.accinfo_query(
                        **args, currency=m.Currency.USD, refresh_cache=True
                    ),
                    "orders": lambda: ctx.history_order_list_query(
                        **args, start=request["start"], end=request["end"]
                    ),
                    "deals": lambda: ctx.history_deal_list_query(
                        **args, start=request["start"], end=request["end"]
                    ),
                }
                for kind, query in queries.items():
                    code, data = query()
                    if code == m.RET_OK:
                        captures[kind] = json.loads(
                            data.to_json(orient="records", double_precision=15)
                        )
                    else:
                        errors[kind] = "query_unavailable"
                # Fees are per order, distinct from executions. Bound requests to provider limits.
                ids = list(
                    dict.fromkeys(
                        str(row["order_id"])
                        for row in captures.get("deals", [])
                        if row.get("order_id")
                    )
                )
                if ids and len(ids) <= 20:
                    code, fees = ctx.order_fee_query(**args, order_id_list=ids)
                    if code == m.RET_OK:
                        captures["fees"] = json.loads(
                            fees.to_json(orient="records", double_precision=15)
                        )
                    else:
                        errors["fees"] = "query_unavailable"
                else:
                    errors["fees"] = "not_requested_or_requires_batches"
                # Query a single clearing date; do not mislabel it as full range coverage.
                code, flows = ctx.get_acc_cash_flow(**args, clearing_date=request["end"])
                if code == m.RET_OK:
                    captures["cash_flows"] = json.loads(
                        flows.to_json(orient="records", double_precision=15)
                    )
                else:
                    errors["cash_flows"] = "query_unavailable"
                result = {
                    "ok": True,
                    "captures": captures,
                    "errors": errors,
                    "cash_flow_date": request["end"],
                    "sdk_version": "10.11.7108",
                }
        finally:
            ctx.close()
except Exception:
    pass
sys.stdout.write(json.dumps(result, allow_nan=False))
