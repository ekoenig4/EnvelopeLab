from envelopelab.materials import FabricLibraryRepository


def test_seed_example_data_populates_expected_fabrics() -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()

    assert repo.fabric_exists("ripstop_nylon")
    assert repo.fabric_exists("polyester")
    assert repo.fabric_exists("nomex")


def test_fabric_lookup_returns_values_with_sources() -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()

    fabric = repo.fabric("nomex")
    assert fabric is not None
    assert fabric.name == "Nomex"
    assert fabric.areal_mass.value == 93.0
    assert fabric.areal_mass.source == "assumed - verify"
    assert repo.fabric("missing") is None
    assert [f.fabric_id for f in repo.fabrics()] == ["nomex", "polyester", "ripstop_nylon"]
    catalog = repo.catalog()
    assert catalog.fabric("nomex") == fabric and catalog.fabrics() == repo.fabrics()


def test_catalog_can_be_used_on_another_thread() -> None:
    import threading

    repo = FabricLibraryRepository()
    repo.seed_example_data()
    catalog = repo.catalog()
    found: list[object] = []
    worker = threading.Thread(target=lambda: found.append(catalog.fabric("polyester")))
    worker.start()
    worker.join()
    assert found == [repo.fabric("polyester")]
