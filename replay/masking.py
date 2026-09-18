"""PII masking for anything written to evidence/replay/ logs (spec §9:
raw member IDs/balances are never written in full to logs or artifacts;
full values exist only in memory during a run)."""


def mask(value) -> str:
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]
