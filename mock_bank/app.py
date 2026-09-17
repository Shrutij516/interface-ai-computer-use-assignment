from flask import Flask, redirect, render_template, request, url_for

from mock_bank.data import MEMBERS, create_sub_account

app = Flask(__name__)

ACCOUNT_TYPES = ("Savings", "Checking", "Money Market")


@app.route("/")
def search():
    return render_template("search.html")


@app.route("/search", methods=["POST"])
def do_search():
    member_id = request.form.get("member_id", "").strip()
    return redirect(url_for("member_detail", member_id=member_id))


@app.route("/members/<member_id>")
def member_detail(member_id):
    member = MEMBERS.get(member_id)
    return render_template("detail.html", member_id=member_id, member=member)


@app.route("/members/<member_id>/subaccounts/new", methods=["GET"])
def new_subaccount_form(member_id):
    member = MEMBERS.get(member_id)
    if member is None:
        return redirect(url_for("member_detail", member_id=member_id))
    return render_template(
        "open_subaccount_form.html", member_id=member_id, member=member, error=None
    )


@app.route("/members/<member_id>/subaccounts/new", methods=["POST"])
def submit_subaccount_form(member_id):
    member = MEMBERS.get(member_id)
    if member is None:
        return redirect(url_for("member_detail", member_id=member_id))

    account_type = request.form.get("account_type", "")
    initial_deposit_raw = request.form.get("initial_deposit", "")

    if account_type not in ACCOUNT_TYPES:
        return render_template(
            "open_subaccount_form.html",
            member_id=member_id,
            member=member,
            error="Please select a valid account type.",
        )

    try:
        initial_deposit = float(initial_deposit_raw)
        if initial_deposit < 0:
            raise ValueError
    except ValueError:
        return render_template(
            "open_subaccount_form.html",
            member_id=member_id,
            member=member,
            error="Initial deposit must be a positive number.",
        )

    return render_template(
        "open_subaccount_confirm.html",
        member_id=member_id,
        member=member,
        account_type=account_type,
        initial_deposit=f"{initial_deposit:.2f}",
    )


@app.route("/members/<member_id>/subaccounts/confirm", methods=["POST"])
def confirm_subaccount(member_id):
    member = MEMBERS.get(member_id)
    if member is None:
        return redirect(url_for("member_detail", member_id=member_id))

    account_type = request.form.get("account_type", "")
    initial_deposit = float(request.form.get("initial_deposit", "0"))
    sub_account = create_sub_account(member_id, account_type, initial_deposit)

    return render_template(
        "open_subaccount_success.html",
        member_id=member_id,
        member=member,
        sub_account=sub_account,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
