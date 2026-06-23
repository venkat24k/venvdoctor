# VenvDoctor

A CLI tool for analyzing Python virtual environments.

## Features

- Detect Python version
- Detect virtual environment path
- Count installed packages
- Analyze package sizes (coming soon)
- Identify storage-heavy dependencies (coming soon)

## Installation

```bash
pip install -e .
```

## Usage

```bash
venvdoctor
```

Example output:

```text
VenvDoctor
==============================
Python Version: 3.14.4
Environment Path: D:\Projects\venvdoctor\venv
Installed Packages: 3
```