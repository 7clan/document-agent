"""Read current OpenRouter key limits without model inference or secret output.

Calls the documented GET /api/v1/key endpoint. Never prints the key, its
metadata, URLs, identifiers, credit amounts, or any provider response body.
This is a *key-level* check; it cannot establish workspace credit balance.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("KEY_STATUS missing GitHub Actions secret")
        return 2
    req = Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=15) as response:
            data = json.load(response).get("data", {})
    except HTTPError as exc:
        print("KEY_STATUS endpoint_denied http_status=" + str(exc.code))
        return 1
    except (URLError, TimeoutError, ValueError, OSError):
        print("KEY_STATUS request_failed_no_model_calls")
        return 1
    if not isinstance(data, dict):
        print("KEY_STATUS unexpected_safe_response_shape")
        return 1

    limit = data.get("limit")
    remaining = data.get("limit_remaining")
    numeric_limit = isinstance(limit, (int, float)) and not isinstance(limit, bool)
    numeric_remaining = isinstance(remaining, (int, float)) and not isinstance(
        remaining, bool)
    if numeric_remaining:
        if remaining <= 0:
            remaining_bucket = "exhausted"
        elif remaining < 0.05:
            remaining_bucket = "low_under_5_cents"
        else:
            remaining_bucket = "positive_at_least_5_cents"
    else:
        remaining_bucket = "not_reported"
    allowed_resets = {"daily", "weekly", "monthly"}
    reset = data.get("limit_reset")
    reset_kind = reset if reset in allowed_resets else "none_or_unknown"

    # Do not log exact remaining credit, key hash, user ID, account details,
    # or the response body on this public repository's GitHub Actions page.
    print("KEY_STATUS " + json.dumps({
        "api_key_authenticated": True,
        "key_spending_cap": "configured" if numeric_limit else "not_configured",
        "key_cap_remaining": remaining_bucket,
        "key_cap_reset": reset_kind,
        "model_requests_sent": 0,
        "account_balance_known": False,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
