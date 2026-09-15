"""CLI: `bench run` measures and stores CSVs, `bench export` renders the markdown ADR."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from bench import ciphers, export, signers
from bench.metrics import MIB

_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS = _ROOT / "benchmarks" / "results"
DEFAULT_DOC = _ROOT / "docs" / "crypto-evaluation.md"


def _run(args: argparse.Namespace) -> None:
    args.results.mkdir(parents=True, exist_ok=True)
    sizes = [int(s * MIB) for s in args.sizes]
    cipher_frame = ciphers.run(
        sizes,
        repeats=args.repeats,
        artifact_path=args.artifact,
        measure_memory=not args.no_memory,
    )
    cipher_frame.to_csv(args.results / "ciphers.csv", index=False)
    signer_frame = signers.run(int(args.message_size * MIB), repeats=args.repeats)
    signer_frame.to_csv(args.results / "signers.csv", index=False)
    print(cipher_frame.to_string(index=False))
    print()
    print(signer_frame.to_string(index=False))


def _export(args: argparse.Namespace) -> None:
    cipher_frame = pd.read_csv(args.results / "ciphers.csv")
    signer_frame = pd.read_csv(args.results / "signers.csv")
    export.write(cipher_frame, signer_frame, args.out)
    print(f"wrote {args.out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="measure ciphers and signers, write CSVs")
    run.add_argument("--sizes", type=float, nargs="+", default=[1, 16], help="MiB per input")
    run.add_argument("--message-size", type=float, default=16, help="MiB signed per scheme")
    run.add_argument("--repeats", type=int, default=5)
    run.add_argument("--artifact", type=Path, help="real artifact to benchmark as well")
    run.add_argument("--no-memory", action="store_true", help="skip subprocess memory probes")
    run.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    run.set_defaults(func=_run)

    exp = sub.add_parser("export", help="render docs/crypto-evaluation.md from CSVs")
    exp.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    exp.add_argument("--out", type=Path, default=DEFAULT_DOC)
    exp.set_defaults(func=_export)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
