"""Guard that every response type carries the envelope.

The envelope was added to 19 TypedDicts by a sweep. Trusting that the sweep reached
all of them - and that a response type added later will not quietly miss it - is
exactly the assumption worth testing.

TypedDicts are erased at runtime, so this checks the declared annotations rather than
any instance: it is a guard against the source drifting, not a runtime behaviour test.
"""

import pytest

from flashalpha_historical import ArchiveAsOf, DataAsOf, types

FEEDS = {
    "node",
    "equity_feed",
    "equity_options_feed",
    "index_feed",
    "index_options_feed",
    "futures_feed",
    "futures_options_feed",
    "flow_feed",
    "oi_feed",
    "macro_feed",
}


def response_types():
    """Every *Response TypedDict declared in the types module."""
    return [
        (name, obj)
        for name, obj in vars(types).items()
        if name.endswith("Response") and isinstance(obj, type) and hasattr(obj, "__annotations__")
    ]


def test_the_guard_actually_finds_response_types():
    # Without this the parametrized tests below would pass vacuously if the module were
    # renamed or the scan broke.
    assert len(response_types()) > 10, f"only found {len(response_types())} response types"


@pytest.mark.parametrize("name,obj", response_types(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_response_type_declares_the_envelope(name, obj):
    annotations = obj.__annotations__
    assert "data_as_of" in annotations, f"{name} is missing data_as_of"
    assert "archive_as_of" in annotations, f"{name} is missing archive_as_of"
    assert "endpoint_version" in annotations, f"{name} is missing endpoint_version"


def test_both_envelope_objects_declare_the_same_feeds():
    """The shape is a contract shared with the live service.

    archive_as_of describes stored rows and data_as_of describes live feeds, but they
    are read the same way and are keyed identically on purpose - a caller should not
    have to branch on which service answered.
    """
    assert set(DataAsOf.__annotations__) == FEEDS
    assert set(ArchiveAsOf.__annotations__) == FEEDS


def test_both_types_are_exported_from_the_package_root():
    import flashalpha_historical

    assert "DataAsOf" in flashalpha_historical.__all__
    assert "ArchiveAsOf" in flashalpha_historical.__all__
