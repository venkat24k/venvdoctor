from venvdoctor.tree import largest_deps


def _tree():
    return {
        "pandas": {"version": "2.2.1", "size_bytes": 100, "deps": ["numpy", "pytz"]},
        "numpy": {"version": "1.26.0", "size_bytes": 200, "deps": []},
        "pytz": {"version": "2024.1", "size_bytes": 10, "deps": []},
        "requests": {"version": "2.31.0", "size_bytes": 50, "deps": []},
    }


def test_largest_deps_sums_own_plus_transitive_size():
    results = largest_deps(_tree(), top_n=10)
    by_name = {r["name"]: r for r in results}

    assert by_name["pandas"]["own_bytes"] == 100
    assert by_name["pandas"]["total_bytes"] == 100 + 200 + 10
    assert by_name["numpy"]["total_bytes"] == 200


def test_largest_deps_respects_top_n():
    results = largest_deps(_tree(), top_n=2)
    assert len(results) == 2
    # pandas (310) should outrank numpy (200), pytz (10), requests (50)
    assert results[0]["name"] == "pandas"


def test_largest_deps_handles_cycles_without_double_counting():
    tree = {
        "a": {"version": "1.0", "size_bytes": 10, "deps": ["b"]},
        "b": {"version": "1.0", "size_bytes": 20, "deps": ["a"]},
    }
    results = largest_deps(tree, top_n=10)
    by_name = {r["name"]: r for r in results}
    # Each package's total should be exactly the sum of both nodes once,
    # not an infinite/duplicated sum from the a<->b cycle.
    assert by_name["a"]["total_bytes"] == 30
    assert by_name["b"]["total_bytes"] == 30


def test_largest_deps_handles_missing_dep_gracefully():
    tree = {
        "a": {"version": "1.0", "size_bytes": 10, "deps": ["does-not-exist"]},
    }
    results = largest_deps(tree, top_n=10)
    assert results[0]["total_bytes"] == 10
