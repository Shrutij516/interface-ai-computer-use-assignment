"""Minimal mocked operator surface (spec §8) -- lists pending intervention
requests, shows the context + screenshot for one, and lets a human mark
it resolved (optionally describing a corrective action they performed on
the live session). The mechanism this triggers (escalation/handoff.py's
blocking wait + resume) is real; this UI is intentionally as plain as
the brief allows.

Run with: python -m escalation.operator_app
"""

from flask import Flask, redirect, render_template_string, request, send_from_directory, url_for

from escalation import store

app = Flask(__name__)

LIST_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Operator Queue</title></head>
<body>
<h1>Pending Intervention Requests</h1>
{% if requests %}
<table border="1" cellpadding="6">
<tr><th>Request ID</th><th>Capability</th><th>Step</th><th>Created</th><th></th></tr>
{% for r in requests %}
<tr>
<td>{{ r.request_id }}</td>
<td>{{ r.capability_id }} v{{ r.version }}</td>
<td>{{ r.step_id }}</td>
<td>{{ r.created_at }}</td>
<td><a href="{{ url_for('view_request', request_id=r.request_id) }}">View</a></td>
</tr>
{% endfor %}
</table>
{% else %}
<p>No pending requests.</p>
{% endif %}
</body>
</html>
"""

DETAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Request {{ r.request_id }}</title></head>
<body>
<h1>Intervention Request: {{ r.request_id }}</h1>
<p><a href="{{ url_for('list_requests') }}">&larr; Back to queue</a></p>
<table border="1" cellpadding="6">
<tr><td>Capability</td><td>{{ r.capability_id }} v{{ r.version }}</td></tr>
<tr><td>Run ID</td><td>{{ r.run_id }}</td></tr>
<tr><td>Failed step</td><td>{{ r.step_id }}</td></tr>
<tr><td>Expected</td><td>{{ r.expected }}</td></tr>
<tr><td>Observed</td><td>{{ r.observed }}</td></tr>
<tr><td>Inputs (masked)</td><td>{{ r.inputs_masked }}</td></tr>
<tr><td>Status</td><td>{{ r.status }}</td></tr>
</table>
<h3>Screenshot at point of failure</h3>
<img src="{{ url_for('screenshot', request_id=r.request_id) }}" style="max-width:800px;border:1px solid #999">
<h3>Live browser</h3>
<p>Live co-browsing view is out of scope (mocked) -- the screenshot above
and the still-open, still-live browser window on the automation host are
the operator's context. Once you've fixed the issue there (or determined
no fix was needed), mark this resolved below.</p>
{% if r.status == "pending" %}
<h3>Mark resolved</h3>
<form method="post" action="{{ url_for('resolve_request', request_id=r.request_id) }}">
<label>Manual action performed (optional, JSON: e.g. {"action": "click", "strategy": "role", "value": "button:Search"})</label><br>
<textarea name="manual_action" rows="3" cols="60"></textarea><br>
<label>Note</label><br>
<textarea name="resolution_note" rows="2" cols="60"></textarea><br>
<button type="submit">Mark Resolved</button>
</form>
{% else %}
<p><strong>Already resolved</strong> at {{ r.resolved_at }}. Final outcome: {{ r.final_outcome or "(automation still resuming)" }}</p>
{% endif %}
</body>
</html>
"""


@app.route("/")
def list_requests():
    return render_template_string(LIST_TEMPLATE, requests=store.list_requests(status="pending"))


@app.route("/requests/<request_id>")
def view_request(request_id):
    return render_template_string(DETAIL_TEMPLATE, r=store.get_request(request_id))


@app.route("/requests/<request_id>/screenshot")
def screenshot(request_id):
    r = store.get_request(request_id)
    screenshot_path = store.REPO_ROOT / r["screenshot_path"]
    return send_from_directory(screenshot_path.parent, screenshot_path.name)


@app.route("/requests/<request_id>/resolve", methods=["POST"])
def resolve_request(request_id):
    import json

    raw_action = request.form.get("manual_action", "").strip()
    manual_action = json.loads(raw_action) if raw_action else None
    resolution_note = request.form.get("resolution_note", "").strip() or None
    store.mark_resolved(request_id, manual_action=manual_action, resolution_note=resolution_note)
    return redirect(url_for("list_requests"))


if __name__ == "__main__":
    app.run(debug=True, port=5050)
