# mock_bank

Target application: a tiny Flask app, server-rendered HTML, in-memory
Python data only. Deliberately legacy-styled (plain HTML tables, no CSS
framework, no test IDs / data-testid attributes, no clean class names) per
`interface-ai-project-spec.md` §1. Three pages:

1. Member search (`/`) — a form with a member ID field
2. Member detail (`/members/<member_id>`) — name + savings balance if
   found, an explicit "No member found" message if not
3. Open sub-account — form (`/members/<member_id>/subaccounts/new`) →
   confirmation screen → success page
   (`/members/<member_id>/subaccounts/confirm`)

Seed data lives in `data.py`: members `10001`, `10002`, `10003` exist;
`40404` is the documented "not found" test case (deliberately not seeded).

## Run it

From the repo root, with dependencies installed (`pip install -r
requirements.txt`):

```
python -m mock_bank.app
```

Then open http://127.0.0.1:5000/ in a browser.
