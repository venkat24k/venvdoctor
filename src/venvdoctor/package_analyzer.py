import importlib.metadata


def get_package_sizes():
    package_sizes = {}

    for dist in importlib.metadata.distributions():

        name = dist.metadata.get("Name", "Unknown")

        if not dist.files:
            continue

        total = 0

        for f in dist.files:
            path = dist.locate_file(f)

            if path.exists() and path.is_file():
                total += path.stat().st_size

        if name not in package_sizes:
            package_sizes[name] = total
        else:
            package_sizes[name] = max(
                package_sizes[name],
                total
            )

    return [
        {
            "name": name,
            "size_bytes": size
        }
        for name, size in package_sizes.items()
    ]