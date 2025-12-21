from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "belajar-secret"  # bebas, untuk session

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

if __name__ == "__main__":
    app.run(debug=True)

@app.route("/menu/<int:n>")
def menu(n):
    if "user" not in session:
        return redirect(url_for("login"))
    return f"Ini halaman Kotak {n} ✅"
