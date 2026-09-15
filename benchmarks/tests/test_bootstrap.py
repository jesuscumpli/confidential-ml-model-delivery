"""Bootstrap sanity check for the benchmarks project."""

from bench import __version__


def test_package_importable() -> None:
    assert __version__ == "0.1.0"
