"""Publish a tampered copy of the artifact for the Layer 2 demo.

Downloads `model.enc` and `model.sig` from the source revision, flips one byte in the
middle of the encrypted artifact, and uploads both files unchanged otherwise to the
`tampered` branch of the same repository. The consumer pointed at that branch must
fail signature verification (exit 4) without attempting decryption.

    uv run python scripts/publish-tampered.py <user>/<repo> [--revision main] [--branch tampered]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download


def flip_middle_byte(data: bytes) -> bytes:
    mutated = bytearray(data)
    mutated[len(mutated) // 2] ^= 0x01
    return bytes(mutated)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_id")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--branch", default="tampered")
    parser.add_argument("--artifact-name", default="model.enc")
    args = parser.parse_args()
    signature_name = Path(args.artifact_name).with_suffix(".sig").name

    api = HfApi()
    artifact = Path(hf_hub_download(args.repo_id, args.artifact_name, revision=args.revision))
    signature = Path(hf_hub_download(args.repo_id, signature_name, revision=args.revision))
    api.create_branch(args.repo_id, branch=args.branch, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tampered = Path(tmp) / args.artifact_name
        tampered.write_bytes(flip_middle_byte(artifact.read_bytes()))
        commit = api.create_commit(
            repo_id=args.repo_id,
            revision=args.branch,
            operations=[
                CommitOperationAdd(path_in_repo=args.artifact_name, path_or_fileobj=tampered),
                CommitOperationAdd(path_in_repo=signature_name, path_or_fileobj=signature),
            ],
            commit_message="Tamper demo: one byte of the encrypted artifact flipped",
        )
    print(f"published tampered {args.artifact_name} to {args.repo_id}@{args.branch} ({commit.oid})")


if __name__ == "__main__":
    main()
