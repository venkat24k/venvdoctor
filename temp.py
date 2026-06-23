import importlib.metadata

for dist in importlib.metadata.distributions():
    print("=" * 50)
    print("Name:", dist.metadata.get("Name"))
    print("Version:", dist.version)
    print("Location:", dist.locate_file(""))