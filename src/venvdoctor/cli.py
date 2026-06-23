from pathlib import Path
import sys
import importlib.metadata


def main():
    print("VenvDoctor")
    print("=" * 30)

    print(f"Python Version: {sys.version.split()[0]}")
    print(f"Python Executable: {sys.executable}")

    venv_path = Path(sys.prefix)

    print(f"Environment Path: {venv_path}")

    packages = list(importlib.metadata.distributions())

    print(f"Installed Packages: {len(packages)}")

    print("\nPackages:")
    for package in sorted(packages, key=lambda p: p.metadata["Name"]):
        print(f" - {package.metadata['Name']}")