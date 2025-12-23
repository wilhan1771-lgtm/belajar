from flask import Flask, render_template, request, redirect, url_for, session
from datetime import date

app = Flask(__name__)
app.secret_key = "belajar-secret"

DEMO_USER = {"username": "admin", "password": "1234"}


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == DEMO_USER["username"] and password == DEMO_USER["password"]:
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            error = "Username / password salah"

    return render_template("login.html", error=error)


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/menu1")
def menu1():
    return render_template("menu1.html")


@app.route("/menu2")
def menu2():
    return render_template("menu2.html")


@app.route("/menu3")
def menu3():
    return render_template("menu3.html")


@app.route("/menu4")
def menu4():
    return render_template("menu4.html")

@app.route("/receiving")
def receiving():
    if "user" not in session:
        return redirect(url_for("login"))
    today = date.today().strftime("%d/%m/%Y")
    return render_template("receiving.html", today=today)

if __name__ == "__main__":
    app.run(debug=True)
