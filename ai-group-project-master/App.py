from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI
from google import genai
from google.genai import types
from supabase import create_client, Client
from io import BytesIO
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"

# 🔥 HARDCODED SUPABASE (KEEPING THIS AS REQUESTED)
SUPABASE_URL = "https://wjlgoigybdkvloalrqct.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndqbGdvaWd5YmRrdmxvYWxycWN0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzcyODYyNzcsImV4cCI6MjA5Mjg2MjI3N30.tBlOO9X0WuTPP4ErJKd4vBvBvlwNTgjFZQPy0xHkXds"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ✅ ENV VARIABLES FOR APIs
client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def is_safe_prompt(text):
    banned_keywords = [
        "suicide", "kill myself", "killing myself", "self harm", "self-harm",
        "cut myself", "hang myself", "overdose", "sexual", "sex", "nude",
        "nudity", "porn", "explicit", "rape", "molest", "incest", "erotic",
        "fetish", "graphic violence", "gore", "dismember", "torture"
    ]

    text = text.lower()
    return not any(word in text for word in banned_keywords)


@app.route("/", methods=["GET", "POST"])
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    story = None
    image_paths = []

    if request.method == "POST":
        user_prompt = request.form.get("prompt")

        if user_prompt:
            if not is_safe_prompt(user_prompt):
                story = "Prompt contains restricted content."
            else:
                story = generate_story(user_prompt)

                if is_safe_prompt(story):
                    image_paths = generate_images_from_story(story)
                    save_story(session["user_id"], user_prompt, story)
                else:
                    story = "Generated story was unsafe."

    return render_template("home.html", story=story, image_paths=image_paths)


@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username and password:
            password_hash = generate_password_hash(password)

            existing = (
                supabase.table("users")
                .select("id")
                .eq("username", username)
                .execute()
            )

            if existing.data:
                message = "Username already exists."
            else:
                supabase.table("users").insert({
                    "username": username,
                    "password_hash": password_hash
                }).execute()

                message = "Registered! Go login."
        else:
            message = "Username and password are required."

    return render_template("register.html", message=message)


@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        result = (
            supabase.table("users")
            .select("id, username, password_hash")
            .eq("username", username)
            .execute()
        )

        if result.data:
            user = result.data[0]

            if check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("home"))

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

    result = (
        supabase.table("stories")
        .select("id, prompt")
        .eq("user_id", session["user_id"])
        .order("id", desc=True)
        .execute()
    )

    stories = [(s["id"], s["prompt"]) for s in result.data]

    return render_template("history.html", stories=stories)


@app.route("/story/<int:story_id>")
def view_story(story_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    result = (
        supabase.table("stories")
        .select("prompt, story")
        .eq("id", story_id)
        .eq("user_id", session["user_id"])
        .execute()
    )

    if result.data:
        story = result.data[0]
        return render_template("story.html", prompt=story["prompt"], story=story["story"])

    return "Story not found", 404


def generate_story(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """
You are a creative writer for a general school-appropriate audience.

STRICT SAFETY RULES:
- No suicide or self-harm
- No sexual content
- No graphic violence
- Keep it PG

Write a story in EXACTLY five paragraphs:

Exposition:
Rising Action:
Climax:
Falling Action:
Resolution:

No extra text outside the story.
"""
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=1200
    )

    story = response.choices[0].message.content

    if not is_safe_prompt(story):
        return "Generated story was unsafe."

    return story


def generate_images_from_story(story):
    labels = [
        "Exposition:",
        "Rising Action:",
        "Climax:",
        "Falling Action:",
        "Resolution:"
    ]

    image_paths = []

    for i, label in enumerate(labels):
        start = story.find(label)
        if start == -1:
            continue

        end = len(story)
        for next_label in labels[i + 1:]:
            idx = story.find(next_label)
            if idx != -1:
                end = idx
                break

        paragraph = story[start:end].replace(label, "").strip()

        if not paragraph or not is_safe_prompt(paragraph):
            continue

        try:
            response = gemini_client.models.generate_images(
                model="imagen-4.0-generate-001",
                prompt=paragraph,
                config=types.GenerateImagesConfig(number_of_images=1)
            )

            image = response.generated_images[0].image

            # Convert to bytes
            image_bytes = BytesIO()
            image.save(image_bytes, format="PNG")
            image_bytes = image_bytes.getvalue()

            file_name = f"{uuid.uuid4().hex}.png"

            # Upload to Supabase bucket
            supabase.storage.from_("story-images").upload(
                file_name,
                image_bytes,
                {"content-type": "image/png"}
            )

            public_url = supabase.storage.from_("story-images").get_public_url(file_name)

            image_paths.append(public_url)

        except Exception as e:
            print("Image error:", e)

    return image_paths


def save_story(user_id, prompt, story):
    supabase.table("stories").insert({
        "user_id": user_id,
        "prompt": prompt,
        "story": story
    }).execute()


if __name__ == "__main__":
    app.run(debug=True)