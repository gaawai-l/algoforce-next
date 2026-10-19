"""Derive the stored on-chain views, and the perp views where they are stored, again under given
rules, from a copy of the stores alone.

Run as `python -m wheelhouse_service.derive --data-dir DIR [--rules SPEC]`. Neither BRK nor an
exchange is ever asked.
"""

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .onchain.brk import BrkClient
from .onchain.store import OnchainStore
from .onchain.sync import VIEWS, OnchainSync
from .perps.store import PerpsStore
from .perps.sync import EXCHANGES, WINDOWS, StoredStates, derive_states, derived_key
from .rules import Rules, parse_rules


def derive_perps(path: Path, rules: Rules) -> list[str] | None:
    """Derive the stored perp views again under `rules`, keeping the time they were computed and
    the grid start they were derived from; return the rules the payloads recorded, or None when
    none were stored."""
    store = PerpsStore(path)
    keys = [derived_key(exchange, window) for exchange in EXCHANGES for window in WINDOWS]
    found = [derived for key in keys if (derived := store.derived(key)) is not None]
    if not found:
        return None
    # One round stores all eight with one time and one start; the latest, should a round have been
    # cut short. The start depends on the worker's horizon, so it is read, not worked out.
    payload, at = max(found, key=lambda derived: derived[1])
    start = int(StoredStates.model_validate_json(payload).start.timestamp())
    derive_states(store, start=start, at=at, rules=rules)
    derived = store.derived(keys[0])
    assert derived is not None
    recorded: list[str] = json.loads(derived[0])["rules"]
    return recorded


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m wheelhouse_service.derive",
        description=(
            "Derive the on-chain views in DIR/onchain.sqlite, and the perp views in "
            "DIR/perps.sqlite when it exists, again under the given rules, from the stored data "
            "only; each view keeps the time it was computed. Only for a copy of the stores: "
            "never point it at the data directory of a running service."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="directory holding a copy of onchain.sqlite, and of perps.sqlite if any",
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
    # Each view with the rules its payload recorded: only those implemented for it apply.
    recorded = [
        f"{view}={','.join(json.loads(derived[0]).get('rules', [])) or 'v1'}"
        for view in VIEWS
        if (derived := store.derived(view)) is not None
    ]
    perps = args.data_dir / "perps.sqlite"
    if perps.is_file() and (applied := derive_perps(perps, rules)) is not None:
        recorded.append(f"perps={','.join(applied) or 'v1'}")
    print(f"derived {' '.join(recorded) or 'none'}")


if __name__ == "__main__":
    main()
