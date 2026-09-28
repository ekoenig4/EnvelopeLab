from envelopelab.materials import FabricLibraryRepository


def test_seed_example_data_populates_expected_fabrics() -> None:
    repo = FabricLibraryRepository()
    repo.seed_example_data()

    assert repo.fabric_exists("ripstop_nylon")
    assert repo.fabric_exists("polyester")
    assert repo.fabric_exists("nomex")
