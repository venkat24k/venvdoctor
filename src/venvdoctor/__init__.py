"""
VenvDoctor
==========
Analyse Python virtual environments.
"""

__version__ = "0.2.0"
__all__ = [
    "get_package_sizes",
    "get_package_detail",
    "get_dependency_tree",
    "find_venvs",
    "scan_all",
    "compare_venvs",
]

from .package_analyzer import get_dependency_tree, get_package_detail, get_package_sizes
from .scanner import compare_venvs, find_venvs, scan_all
