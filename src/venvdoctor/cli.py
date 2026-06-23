from pathlib import Path
from .package_analyzer import get_package_sizes
import sys


def main():
    print("VenvDoctor")
    print("=" * 30)

    print(f"Python Version: {sys.version.split()[0]}")
    print(f"Python Executable: {sys.executable}")

    venv_path = Path(sys.prefix)

    print(f"Environment Path: {venv_path}")

    packages = get_package_sizes()

    total_size_bytes = sum(
        pkg["size_bytes"]
        for pkg in packages
    )

    total_size_mb = total_size_bytes / (1024 * 1024)

    print(f"Installed Packages: {len(packages)}")
    print(f"Environment Size: {total_size_mb:.2f} MB")

    print("\nPackages:")
    for package in sorted(packages, key=lambda p: p["name"]):
        print(f" - {package['name']}")

    packages.sort(
        key=lambda x: x["size_bytes"],
        reverse=True
    )

    print("\nLargest Packages")
    print("=" * 30)

    for pkg in packages[:10]:
        size_mb = pkg["size_bytes"] / (1024 * 1024)

        percentage = (
            pkg["size_bytes"]
            / total_size_bytes
        ) * 100

        print(
            f"{pkg['name']:<20} "
            f"{size_mb:.2f} MB "
            f"({percentage:.1f}%)"
        )