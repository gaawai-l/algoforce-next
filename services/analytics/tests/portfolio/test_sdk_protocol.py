"""Exercise the SDK subprocess protocol with a boundary fake, without account access."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/broker/moomoo_reader.py"


def test_sdk_protocol_selects_explicit_sg_real_account_and_only_calls_queries(tmp_path):
    fake = tmp_path / "moomoo.py"
    fake.write_text("""
import json
RET_OK=0
class Values:
    NONE="NONE"; FUTUSG="FUTUSG"; REAL="REAL"; USD="USD"
TrdMarket=SecurityFirm=TrdEnv=Currency=Values
class SysConfig:
    @staticmethod
    def set_all_thread_daemon(value): pass
    @staticmethod
    def enable_console_log(value): pass
class Table:
    def __init__(self,rows): self.rows=rows
    def to_json(self,**kwargs): return json.dumps(self.rows)
class OpenSecTradeContext:
    def __init__(self,**kwargs):
        assert kwargs==dict(filter_trdmarket="NONE",host="127.0.0.1",
                           port=11111,security_firm="FUTUSG")
    def get_acc_list(self):
        return 0,Table([dict(acc_id=17,trd_env="REAL",security_firm="FUTUSG",
            acc_status="DISABLED",trdmarket_auth=["US"]),
            dict(acc_id=18,trd_env="SIMULATE",security_firm="FUTUSG",
            acc_status="ACTIVE",trdmarket_auth=["US"])])
    def read(self,**kwargs):
        assert kwargs["acc_id"]==17 and kwargs["trd_env"]=="REAL"
        return 0,Table([])
    position_list_query=accinfo_query=history_order_list_query=history_deal_list_query=read
    def get_acc_cash_flow(self,**kwargs):
        assert kwargs==dict(acc_id=17,trd_env="REAL",start="2026-09-01",end="2026-09-20")
        return 0,Table([dict(cashflow_id="range-flow",create_time="2026-09-02 09:00:00",
                            clearing_date="2026-09-03",currency="USD",cashflow_amount=100)])
    def order_fee_query(self,**kwargs):
        assert kwargs["acc_id"]==17 and kwargs["trd_env"]=="REAL"
        assert 1 <= len(kwargs["order_id_list"]) <= 20
        return 0,Table([dict(order_id=value,fee_amount=1) for value in kwargs["order_id_list"]])
    def close(self): pass
""")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    accounts = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps({"operation": "accounts"}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    value = json.loads(accounts.stdout)
    assert [a["account_id"] for a in value["accounts"]] == ["17"]
    assert value["accounts"][0]["status"] == "DISABLED"
    response = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(
            {"operation": "sync", "account_id": "17", "start": "2026-09-01", "end": "2026-09-20"}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    captured = json.loads(response.stdout)
    assert captured["ok"] is True
    assert captured["captures"]["cash_flows"][0]["cashflow_id"] == "range-flow"
    assert captured["captures"]["_coverage"]["cash_flows"] == {
        "start": "2026-09-01",
        "end": "2026-09-20",
        "basis": "creation_date",
        "query_succeeded": True,
    }
    wrong = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(
            {"operation": "sync", "account_id": "18", "start": "2026-09-01", "end": "2026-09-20"}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(wrong.stdout)["ok"] is False
    denied = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps({"operation": "place_order"}),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(denied.stdout)["ok"] is False

    fee_response = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(
            {"operation": "fees", "account_id": "17", "order_ids": [str(i) for i in range(20)]}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert len(json.loads(fee_response.stdout)["fees"]) == 20
    overflow = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(
            {"operation": "fees", "account_id": "17", "order_ids": [str(i) for i in range(21)]}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert json.loads(overflow.stdout)["ok"] is False
