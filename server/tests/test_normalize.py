"""Tests for response normalisation.

The API is undocumented and its field names have moved before, so these tests
pin the shapes we accept. Both the nested (`store.store_name`) and flat
(`store_name`) forms are exercised, because we cannot be certain which one a
given TGTG version returns.
"""

from tgtg_alert.tgtg_source import normalize_item, normalize_page


NESTED = {
    "item_id": "123456",
    "display_name": "Magic Bag",
    "item_category": "MEALS",
    "items_available": 3,
    "in_sales_window": True,
    "price_including_taxes": {"code": "EUR", "minor_units": 399, "decimals": 2},
    "pickup_interval": {"start": "2026-10-13T18:00:00Z", "end": "2026-10-13T19:00:00Z"},
    "store": {"store_id": "999", "store_name": "Blank Street", "distance": 850},
}

FLAT = {
    "item_id": 987,
    "name": "Bakery Box",
    "items_available": 0,
    "store_name": "Pret A Manger",
    "price_including_taxes": 4.5,
}


def test_normalizes_nested_store_shape():
    item = normalize_item(NESTED)
    assert item is not None
    assert item.item_id == "123456"
    assert item.quantity == 3
    assert item.store_id == "999"
    assert item.store_name == "Blank Street"
    assert item.display_name == "Magic Bag"
    assert item.price_minor == 399
    assert item.currency == "EUR"
    assert item.distance_m == 850
    assert item.pickup_end == "2026-10-13T19:00:00Z"


def test_normalizes_flat_shape_and_coerces_id_to_string():
    item = normalize_item(FLAT)
    assert item is not None
    assert item.item_id == "987"          # int in, str out -- ids are compared as strings
    assert item.quantity == 0
    assert item.store_name == "Pret A Manger"
    assert item.display_name == "Bakery Box"
    assert item.price_minor == 450        # a bare float is treated as major units


def test_item_without_id_is_dropped():
    assert normalize_item({"display_name": "ghost"}) is None


def test_non_dict_is_dropped():
    assert normalize_item("nonsense") is None
    assert normalize_item(None) is None


def test_missing_quantity_defaults_to_zero():
    item = normalize_item({"item_id": "1"})
    assert item is not None
    assert item.quantity == 0


def test_negative_quantity_is_clamped():
    item = normalize_item({"item_id": "1", "items_available": -4})
    assert item is not None
    assert item.quantity == 0


def test_garbage_quantity_degrades_to_zero():
    item = normalize_item({"item_id": "1", "items_available": "many"})
    assert item is not None
    assert item.quantity == 0


def test_page_keeps_good_items_and_drops_bad_ones():
    items = normalize_page([NESTED, {"no_id": True}, FLAT, "junk"])
    assert len(items) == 2
    assert [i.item_id for i in items] == ["123456", "987"]


def test_page_tolerates_non_list():
    assert normalize_page(None) == []
    assert normalize_page({"items": []}) == []


def test_price_object_without_minor_units_falls_back_to_amount():
    item = normalize_item(
        {"item_id": "1", "price_including_taxes": {"amount": 3.5, "decimals": 2}}
    )
    assert item is not None
    assert item.price_minor == 350
