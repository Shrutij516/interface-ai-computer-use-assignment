"""In-memory seed data for the mock bank app. No database, no persistence."""

MEMBERS = {
    "10001": {"name": "Alice Johnson", "savings_balance": 15234.56, "sub_accounts": []},
    "10002": {"name": "Bob Martinez", "savings_balance": 892.10, "sub_accounts": []},
    "10003": {"name": "Priya Shah", "savings_balance": 100234.00, "sub_accounts": []},
}

# Intentionally not present in MEMBERS above — the documented "not found" test case.
NOT_FOUND_TEST_ID = "40404"

_next_account_number = 500001


def create_sub_account(member_id: str, account_type: str, initial_deposit: float) -> dict:
    global _next_account_number
    sub_account = {
        "account_number": str(_next_account_number),
        "account_type": account_type,
        "initial_deposit": initial_deposit,
    }
    _next_account_number += 1
    MEMBERS[member_id]["sub_accounts"].append(sub_account)
    return sub_account
