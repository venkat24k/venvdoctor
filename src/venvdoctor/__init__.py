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
    "score_environment",
    "find_venvs",
    "scan_all",
]

from .package_analyzer import get_package_sizes, get_package_detail, get_dependency_tree
from .scanner import find_venvs, scan_all