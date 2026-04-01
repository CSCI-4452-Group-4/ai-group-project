from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from openai import OpenAI
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# Initialize Groq client (OpenAI-compatible)
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)


def init_db():
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        prompt TEXT NOT NULL,
        story TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    story = None

    if request.method == "POST":
        user_prompt = request.form.get("prompt")

        if user_prompt:
            story = generate_story(user_prompt)
            save_story(session["user_id"], user_prompt, story)

    return render_template("home.html", story=story)


@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username and password:
            password_hash = generate_password_hash(password)

            conn = sqlite3.connect("app.db")
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash)
                )
                conn.commit()
                message = "Registered! Go login."
            except sqlite3.IntegrityError:
                message = "Username already exists."

            conn.close()
        else:
            message = "Username and password are required."

    return render_template("register.html", message=message)


@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect("app.db")
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,)
        )

        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session["user_id"] = user[0]
            session["username"] = username
            return redirect(url_for("home"))
        else:
            message = "Invalid login"

    return render_template("login.html", message=message)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, prompt FROM stories WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],)
    )
    stories = cursor.fetchall()

    conn.close()

    return render_template("history.html", stories=stories)


@app.route("/story/<int:story_id>")
def view_story(story_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT prompt, story FROM stories WHERE id = ? AND user_id = ?",
        (story_id, session["user_id"])
    )
    row = cursor.fetchone()

    conn.close()

    if row:
        return render_template("story.html", prompt=row[0], story=row[1])
    else:
        return "Story not found or access denied.", 404


def generate_story(prompt):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a creative writer. Write a short story."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.8,
            max_tokens=1000
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"Error: {str(e)}"


def save_story(user_id, prompt, story):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO stories (user_id, prompt, story) VALUES (?, ?, ?)",
        (user_id, prompt, story)
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    app.run(debug=True)