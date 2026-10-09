import pytest

from fireant_crawler.client.whitelist import is_allowed


@pytest.mark.parametrize(
    "path",
    [
        "/instruments",
        "/symbols/search",
        "/symbols/VOS",
        "/symbols/VOS/historical-quotes",
        "/symbols/HNX-INDEX/historical-quotes",
        "/symbols/VOS/timescale-marks",
        "/symbols/VOS/fundamental",
        "/symbols/VOS/dividends",
        "/events/search",
        "/icb",
        "/icb/8350/symbols",
        "/symbols/E1VFVN30",
        "/symbols/VN30/historical-quotes",
    ],
)
def test_allows_market_data_paths(path):
    assert is_allowed("GET", path)


@pytest.mark.parametrize(
    "path",
    [
        "/broker-users/1/accounts/2/orderHistory",
        "/me/screeners",
        "/admin/ir/companies",
        "/symbols/VOS/historical-quotes/extra",
        "/symbols/../me/screeners",
        "/symbols/VOS?x=1",
        "/symbols/VOS%2Fhistorical-quotes",
        "symbols/VOS",
        "https://evil.example/symbols/VOS",
        "/symbols/all-financial-data",          # lower-case endpoint names are not tickers
        "/symbols/vos",
        "/symbols/VOS-",
        "/symbols/-VOS",
        "/symbols/A-B-C",
        "/symbols/ABCDEFGHIJKLMNOPQRSTU",       # 21 characters
        "/icb/abc/symbols",
        "/icb/8350-x/symbols",
    ],
)
def test_rejects_other_paths(path):
    assert not is_allowed("GET", path)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD"])
def test_rejects_orders_endpoint_and_any_non_get(method):
    assert not is_allowed(method, "/symbols/VOS/historical-quotes")
