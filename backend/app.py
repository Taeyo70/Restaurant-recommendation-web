from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import json
import tempfile
import time
from threading import Lock

from openpyxl import load_workbook
from werkzeug.security import generate_password_hash, check_password_hash

import os

try:
    import ollama
    ollama_client = ollama.Client(
        host="http://127.0.0.1:11434",
        timeout=8,
    )
except ImportError:
    ollama = None
    ollama_client = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "restaurants.db")
AUTH_WORKBOOK = os.environ.get(
    "RESTAURANT_WORKBOOK",
    os.path.abspath(
        os.path.join(BASE_DIR, "..", "data", "restaurants_final_with_maps.xlsx")
    ),
)
AUTH_LOCK = Lock()


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _open_auth_workbook():
    if not os.path.exists(AUTH_WORKBOOK):
        raise FileNotFoundError(f"Workbook not found: {AUTH_WORKBOOK}")

    workbook = load_workbook(AUTH_WORKBOOK)

    if "users" not in workbook.sheetnames:
        users = workbook.create_sheet("users")
        users.append(["id", "username", "email", "password_hash", "created_at"])

    return workbook


def _save_auth_workbook(workbook):
    directory = os.path.dirname(AUTH_WORKBOOK) or "."
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix="foodfinder-auth-",
        suffix=".xlsx",
    )
    os.close(file_descriptor)

    try:
        workbook.save(temporary_path)
        workbook.close()
        os.replace(temporary_path, AUTH_WORKBOOK)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def init_auth_sheets():
    with AUTH_LOCK:
        if not os.path.exists(AUTH_WORKBOOK):
            raise FileNotFoundError(f"Workbook not found: {AUTH_WORKBOOK}")

        workbook = load_workbook(AUTH_WORKBOOK)
        if "users" in workbook.sheetnames:
            workbook.close()
            return

        users = workbook.create_sheet("users")
        users.append(["id", "username", "email", "password_hash", "created_at"])
        _save_auth_workbook(workbook)


def find_user(identifier):
    with AUTH_LOCK:
        workbook = _open_auth_workbook()
        users = workbook["users"]
        user = None

        for row in users.iter_rows(min_row=2, values_only=True):
            if row[1] == identifier or str(row[2]).lower() == identifier.lower():
                user = {
                    "id": row[0],
                    "username": row[1],
                    "email": row[2],
                    "password_hash": row[3],
                }
                break

        workbook.close()
        return user


def find_user_by_email(email):
    return find_user(email)


init_auth_sheets()


# =========================
# LOGIN PAGE
# =========================

@app.route("/")
def login():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def do_login():
    identifier = request.form.get("identifier", "").strip()
    password = request.form.get("password", "")

    user = find_user(identifier)

    if user is None or not check_password_hash(
        user["password_hash"],
        password
    ):
        return render_template(
            "login.html",
            error="Invalid username/email or password."
        )

    session["user_id"] = user["id"]
    session["username"] = user["username"]

    return redirect(url_for("home"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = find_user(session.get("username", ""))
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    return render_template("profile.html", user=user)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/favorites")
def favorites():
    return render_template("favorites.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if len(username) < 3:
        return render_template(
            "register.html",
            error="Username must contain at least 3 characters."
        )

    if len(password) < 8:
        return render_template(
            "register.html",
            error="Password must contain at least 8 characters."
        )

    password_hash = generate_password_hash(password)

    with AUTH_LOCK:
        workbook = _open_auth_workbook()
        users = workbook["users"]

        for row in users.iter_rows(min_row=2, values_only=True):
            if row[1] == username or str(row[2]).lower() == email:
                workbook.close()
                return render_template(
                    "register.html",
                    error="Username or email already exists."
                )

        user_ids = [row[0] for row in users.iter_rows(min_row=2, values_only=True) if row[0]]
        next_id = max(user_ids, default=0) + 1
        users.append([next_id, username, email, password_hash, int(time.time())])
        _save_auth_workbook(workbook)
        workbook.close()

    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = request.form.get("email", "").strip().lower()

    new_password = request.form.get("password", "")

    if len(new_password) < 8:
        return render_template(
            "forgot_password.html",
            error="Password must contain at least 8 characters."
        )

    password_hash = generate_password_hash(new_password)
    updated = False

    with AUTH_LOCK:
        workbook = _open_auth_workbook()
        users = workbook["users"]

        for row in users.iter_rows(min_row=2):
            if str(row[2].value).lower() == email:
                row[3].value = password_hash
                updated = True
                break

        _save_auth_workbook(workbook)
        workbook.close()

    if not updated:
        return render_template(
            "forgot_password.html",
            error="No account was found with that email address."
        )

    return render_template(
        "forgot_password.html",
        message="Your password was changed. You can now log in."
    )

# =========================
# HOME PAGE
# =========================

@app.route("/home")
def home():

    conn = get_db()

    # Total restaurants
    total_restaurants = conn.execute(
        "SELECT COUNT(*) FROM restaurants"
    ).fetchone()[0]

    # Total cities
    total_cities = conn.execute(
        "SELECT COUNT(DISTINCT City) FROM restaurants"
    ).fetchone()[0]

    # Average rating
    avg_rating = conn.execute(
        "SELECT ROUND(AVG(Rating), 1) FROM restaurants"
    ).fetchone()[0]

    # Average cost
    avg_cost = conn.execute(
        "SELECT ROUND(AVG(Cost), 0) FROM restaurants"
    ).fetchone()[0]

    # =========================
    # RESTAURANTS PER CITY
    # =========================

    city_data = conn.execute("""
        SELECT
            City,
            COUNT(*) AS total,
            ROUND(AVG(Rating), 2) AS rating
        FROM restaurants
        WHERE City IS NOT NULL
        GROUP BY City
        ORDER BY total DESC
        LIMIT 8
    """).fetchall()

    city_data = [dict(row) for row in city_data]

    # Calculate bar percentages in Python
    if city_data:
        highest_city_total = city_data[0]["total"]

        for city in city_data:
            city["percentage"] = round(
                (city["total"] / highest_city_total) * 100
            )

    # =========================
    # MOST COMMON CUISINES
    # =========================

    cuisine_data = conn.execute("""
        SELECT
            Cuisine,
            COUNT(*) AS total
        FROM restaurants
        WHERE Cuisine IS NOT NULL
        GROUP BY Cuisine
        ORDER BY total DESC
        LIMIT 8
    """).fetchall()

    cuisine_data = [dict(row) for row in cuisine_data]

    # Calculate bar percentages in Python
    if cuisine_data:
        highest_cuisine_total = cuisine_data[0]["total"]

        for cuisine in cuisine_data:
            cuisine["percentage"] = round(
                (cuisine["total"] / highest_cuisine_total) * 100
            )

    conn.close()

    return render_template(
        "home.html",
        total_restaurants=total_restaurants,
        total_cities=total_cities,
        avg_rating=avg_rating,
        avg_cost=avg_cost,
        city_data=city_data,
        cuisine_data=cuisine_data
    )


# =========================
# SEARCH PAGE
# =========================

@app.route("/search")
def search():

    keyword = request.args.get("keyword", "").strip()
    city = request.args.get("city", "").strip()
    cuisine = request.args.get("cuisine", "").strip()
    max_cost = request.args.get("max_cost", "").strip()
    min_rating = request.args.get("min_rating", "").strip()

    conn = get_db()

    query = "SELECT * FROM restaurants WHERE 1=1"
    params = []

    if keyword:
        text = keyword.lower()

        # Check if keyword specifies a city
        cities = conn.execute("SELECT DISTINCT City FROM restaurants").fetchall()
        found_city = None
        for row in cities:
            if row["City"] and row["City"].lower() in text:
                found_city = row["City"]
                break

        if found_city and not city:
            query += " AND City = ?"
            params.append(found_city)

        search_term = text.replace("restaurants", "").replace("restaurant", "").replace(" in ", " ").strip()
        if search_term and not found_city:
            query += """
                AND (
                    Name LIKE ?
                    OR Cuisine LIKE ?
                    OR City LIKE ?
                    OR Location LIKE ?
                )
            """
            value = "%" + search_term + "%"
            params.extend([value, value, value, value])

    if city:
        query += " AND City = ?"
        params.append(city)

    if cuisine:
        query += " AND Cuisine LIKE ?"
        params.append("%" + cuisine + "%")

    if max_cost:
        try:
            query += " AND Cost <= ?"
            params.append(float(max_cost))
        except ValueError:
            pass

    if min_rating:
        try:
            query += " AND Rating >= ?"
            params.append(float(min_rating))
        except ValueError:
            pass

    query += " ORDER BY Rating DESC LIMIT 60"

    restaurants = conn.execute(query, params).fetchall()

    cities = conn.execute("""
        SELECT DISTINCT City
        FROM restaurants
        WHERE City IS NOT NULL AND City != ''
        ORDER BY City
    """).fetchall()

    cuisines_raw = conn.execute("""
        SELECT DISTINCT Cuisine
        FROM restaurants
        WHERE Cuisine IS NOT NULL AND Cuisine != ''
    """).fetchall()

    # Extract distinct individual cuisines
    cuisine_set = set()
    for row in cuisines_raw:
        if row["Cuisine"]:
            for item in row["Cuisine"].split(","):
                c = item.strip()
                if c:
                    cuisine_set.add(c)
    sorted_cuisines = sorted(list(cuisine_set))

    conn.close()

    return render_template(
        "search.html",
        restaurants=restaurants,
        cities=cities,
        cuisines=sorted_cuisines,
        selected_city=city,
        selected_cuisine=cuisine,
        selected_cost=max_cost,
        selected_rating=min_rating,
        keyword=keyword
    )


@app.route("/ai-search", methods=["POST"])
def ai_search():
    user_query = request.form.get("query", "").strip()

    if not user_query:
        return redirect(url_for("search"))

    prompt = f"""
Convert this restaurant request into JSON filters:

Request: {user_query}

Return only valid JSON with these fields:
{{
    "keyword": "",
    "city": "",
    "cuisine": "",
    "max_cost": "",
    "min_rating": ""
}}

Rules:
- Put food or restaurant names in keyword.
- Put the city separately in city.
- Put cuisine separately in cuisine.
- Use numbers only for max_cost and min_rating.
- Use empty strings when information is missing.
"""

    try:
        response = ollama_client.chat(
            model="qwen2.5:3b",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            format="json"
        )

        filters = json.loads(response["message"]["content"])

    except Exception:
        return redirect(url_for("search", keyword=user_query))

    allowed_filters = [
        "keyword",
        "city",
        "cuisine",
        "max_cost",
        "min_rating"
    ]

    cleaned_filters = {
        key: filters.get(key, "")
        for key in allowed_filters
        if filters.get(key, "") not in ("", None)
    }

    return redirect(url_for("search", **cleaned_filters))

MOOD_KEYWORDS = {
    "Comfort food": ["Biryani", "North Indian", "Fast Food", "Chinese"],
    "Date night": ["Italian", "Continental", "Cafe"],
    "Healthy": ["Healthy", "Salad", "Vegan", "Vegetarian"],
    "Spicy": ["Indian", "Mexican", "Thai", "Biryani"],
    "Quick bite": ["Fast Food", "Burger", "Pizza", "Street Food"],
    "Sweet craving": ["Dessert", "Bakery", "Ice Cream", "Cafe"],
}

MEAL_KEYWORDS = {
    "Breakfast": ["Breakfast", "Cafe", "Bakery"],
    "Snacks": ["Fast Food", "Street Food", "Cafe"],
    "Dinner": ["Dinner", "Fine Dining", "North Indian", "Chinese"],
}

DIET_KEYWORDS = {
    "Vegetarian": ["Vegetarian", "South Indian", "North Indian", "Jain", "Pure Veg"],
    "Vegan": ["Vegan", "Salad", "Health Food", "Juice"],
    "Non-veg": ["Mughlai", "Kebab", "Tandoori", "Seafood", "Biryani", "Chicken", "Mutton", "Fish"],
}


@app.route("/recommendations", methods=["GET", "POST"])
@app.route("/recommend", methods=["POST"])
def recommendations():
    preferences = {
        "city": request.form.get("city", "").strip(),
        "mood": request.form.get("mood", "").strip(),
        "meal": request.form.get("meal", "").strip(),
        "cuisine": request.form.get("cuisine", "").strip(),
        "diet": request.form.get("diet", "").strip(),
        "max_cost": request.form.get("max_cost", "").strip(),
        "min_rating": request.form.get("min_rating", "").strip(),
    }

    if request.method == "GET":
        return render_template(
            "recommendations.html",
            preferences=preferences,
            restaurants=[],
            searched=False,
        )

    session["preferences"] = preferences
    conditions = ["1=1"]
    params = []

    if preferences["city"]:
        conditions.append("City LIKE ?")
        params.append("%" + preferences["city"] + "%")

    if preferences["cuisine"]:
        conditions.append("Cuisine LIKE ?")
        params.append("%" + preferences["cuisine"] + "%")

    terms = MOOD_KEYWORDS.get(preferences["mood"], [])
    terms += MEAL_KEYWORDS.get(preferences["meal"], [])
    terms = list(dict.fromkeys(terms))
    if terms:
        term_conditions = []
        for term in terms:
            term_conditions.append("(Cuisine LIKE ? OR Name LIKE ?)")
            params.extend(["%" + term + "%", "%" + term + "%"])
        conditions.append("(" + " OR ".join(term_conditions) + ")")

    if preferences["diet"] and preferences["diet"] != "No preference":
        diet_terms = DIET_KEYWORDS.get(preferences["diet"], [preferences["diet"]])
        diet_conditions = []
        for term in diet_terms:
            diet_conditions.append("(Cuisine LIKE ? OR Name LIKE ?)")
            params.extend(["%" + term + "%", "%" + term + "%"])
        conditions.append("(" + " OR ".join(diet_conditions) + ")")

    try:
        if preferences["max_cost"]:
            conditions.append("Cost <= ?")
            params.append(float(preferences["max_cost"]))
    except ValueError:
        preferences["max_cost"] = ""

    try:
        if preferences["min_rating"]:
            conditions.append("Rating >= ?")
            params.append(float(preferences["min_rating"]))
    except ValueError:
        preferences["min_rating"] = ""

    query = f"""
        SELECT Name, Location, City, Cuisine, Rating, Votes, Cost, "Google Maps Link"
        FROM restaurants
        WHERE {' AND '.join(conditions)}
        ORDER BY Rating DESC, Votes DESC
        LIMIT 12
    """

    conn = get_db()
    restaurants = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()

    reasons = {}
    ai_message = "Showing database matches."
    if restaurants and ollama_client:
        prompt = f"""
Give a short reason why each restaurant matches these preferences.
Preferences: {json.dumps(preferences)}
Restaurants: {json.dumps(restaurants[:6])}
Return only JSON: {{"reasons": [{{"name": "", "reason": ""}}]}}
"""
        try:
            response = ollama_client.chat(
                model="qwen2.5:1.5b",
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            result = json.loads(response["message"]["content"])
            reasons = {item["name"]: item["reason"] for item in result.get("reasons", [])}
            ai_message = "Ollama personalized the explanations for these matches."
        except Exception:
            reasons = {}
            ai_message = "Showing database matches because Ollama took too long or was unavailable."
    elif restaurants:
        ai_message = "Showing database matches. Ollama AI explanations are unavailable."
    else:
        ai_message = "No matches found. Try changing your preferences."

    for restaurant in restaurants:
        restaurant["reason"] = reasons.get(
            restaurant["Name"],
            "Matches your selected preferences and restaurant rating."
        )

    return render_template(
        "recommendations.html",
        preferences=preferences,
        restaurants=restaurants,
        searched=True,
        ai_message=ai_message,
    )

# =========================
# RUN APPLICATION
# =========================

if __name__ == "__main__":
    app.run(debug=True)
