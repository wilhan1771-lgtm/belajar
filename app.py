from flask import Flask, render_template, request

app = Flask(__name__)

DEMO_USER = {"username": "admin", "password": "1234"}

@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == DEMO_USER["username"] and password == DEMO_USER["password"]:
            return "Login berhasil ✅"
        else:
            error = "Username / password salah"

    return render_template("login.html", error=error)

if __name__ == "__main__":
    app.run(debug=True)
