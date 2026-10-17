"""Derive the stored on-chain views again under given rules, from a copy of the store alone.

Run as `python -m wheelhouse_service.derive --data-dir DIR [--rules SPEC]`. BRK is never asked.
"""

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from .onchain.brk import BrkClient
from .onchain.store import OnchainStore
from .onchain.sync import VIEWS, OnchainSync
from .rules import parse_rules


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m wheelhouse_service.derive",
        description=(
            "Derive the on-chain views in DIR/onchain.sqlite again under the given rules, from "
            "the stored series and snapshots only; each view keeps the time it was computed. "
            "Only for a copy of the store: never point it at the data directory of a running "
            "service."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="directory holding a copy of onchain.sqlite",
    )
    parser.add_argument(
        "--rules",
        help="comma-separated O1-O6, or v1 for none; defaults to WHEELHOUSE_RULES (unset: all)",
    )
    args = parser.parse_args(argv)
    try:
        rules = parse_rules(
            args.rules if args.rules is not None else os.environ.get("WHEELHOUSE_RULES")
        )
    except ValueError as exc:
        parser.error(str(exc))
    path = args.data_dir / "onchain.sqlite"
    if not path.is_file():
        parser.error(f"{path} does not exist")
    store = OnchainStore(path)
    # The worker needs a client, but deriving from the store never uses it.
    OnchainSync(store, BrkClient(), rules=rules).derive_from_store()
    views = [view for view in VIEWS if store.derived(view) is not None]
    print(f"derived views={','.join(views) or 'none'} rules={','.join(sorted(rules)) or 'v1'}")


if __name__ == "__main__":
    main()
