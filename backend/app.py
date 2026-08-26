from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import json
import tempfile
import time
from threading import Lock
import os
import urllib.request
import urllib.error

from openpyxl import load_workbook
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "restaurants.db")

AUTH_WORKBOOK = os.environ.get(
    "RESTAURANT_WORKBOOK",
    os.path.abspath(
        os.path.join(
            BASE_DIR,
            "..",
            "data",
            "restaurants_final_with_maps.xlsx"
        )
    ),
)

AUTH_LOCK = Lock()

# ============================================================
# AI / OPENROUTER
# ============================================================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

AI_MODEL = "qwen/qwen3-8b:free"


def ask_ai(prompt):
    """
    Send a prompt to OpenRouter and return the AI text response.
    """

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured."
        )

    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 700
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://restaurant-finder.onrender.com",
            "X-Title": "Restaurant Finder",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="ignore")
        print("OpenRouter HTTP error:", error.code, error_body)
        raise RuntimeError(
            f"OpenRouter HTTP error {error.code}"
        )

    except urllib.error.URLError as error:
        print("OpenRouter connection error:", error)
        raise RuntimeError(
            "Could not connect to OpenRouter."
        )

    except Exception as error:
        print("OpenRouter error:", error)
        raise

    try:
        return response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("Unexpected OpenRouter response:", response_data)
        raise RuntimeError(
            "Invalid response received from OpenRouter."
        )


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# AUTH WORKBOOK
# ============================================================

def _open_auth_workbook():

    if not os.path.exists(AUTH_WORKBOOK):
        raise FileNotFoundError(
            f"Workbook not found: {AUTH_WORKBOOK}"
        )

    workbook = load_workbook(AUTH_WORKBOOK)

    if "users" not in workbook.sheetnames:

        users = workbook.create_sheet("users")

        users.append([
            "id",
            "username",
            "email",
            "password_hash",
            "created_at"
        ])

    return workbook


def _save_auth_workbook(workbook):

    directory = (
        os.path.dirname(AUTH_WORKBOOK)
        or "."
    )

    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory,
        prefix="restaurant-finder-auth-",
        suffix=".xlsx",
    )

    os.close(file_descriptor)

    try:

        workbook.save(temporary_path)
        workbook.close()

        os.replace(
            temporary_path,
            AUTH_WORKBOOK
        )

    finally:

        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def init_auth_sheets():

    with AUTH_LOCK:

        if not os.path.exists(AUTH_WORKBOOK):
            raise FileNotFoundError(
                f"Workbook not found: {AUTH_WORKBOOK}"
            )

        workbook = load_workbook(
            AUTH_WORKBOOK
        )

        if "users" in workbook.sheetnames:

            workbook.close()
            return

        users = workbook.create_sheet(
            "users"
        )

        users.append([
            "id",
            "username",
            "email",
            "password_hash",
            "created_at"
        ])

        _save_auth_workbook(workbook)


def find_user(identifier):

    with AUTH_LOCK:

        workbook = _open_auth_workbook()

        users = workbook["users"]

        user = None

        for row in users.iter_rows(
            min_row=2,
            values_only=True
        ):

            if (
                row[1] == identifier
                or str(row[2]).lower()
                == identifier.lower()
            ):

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


# ============================================================
# LOGIN
# ============================================================

@app.route("/")
def login():

    return render_template(
        "login.html"
    )


@app.route("/login", methods=["POST"])
def do_login():

    identifier = request.form.get(
        "identifier",
        ""
    ).strip()

    password = request.form.get(
        "password",
        ""
    )

    user = find_user(identifier)

    if (
        user is None
        or not check_password_hash(
            user["password_hash"],
            password
        )
    ):

        return render_template(
            "login.html",
            error="Invalid username/email or password."
        )

    session["user_id"] = user["id"]
    session["username"] = user["username"]

    return redirect(
        url_for("home")
    )


# ============================================================
# PROFILE
# ============================================================

@app.route("/profile")
def profile():

    if not session.get("user_id"):
        return redirect(
            url_for("login")
        )

    user = find_user(
        session.get(
            "username",
            ""
        )
    )

    if user is None:

        session.clear()

        return redirect(
            url_for("login")
        )

    return render_template(
        "profile.html",
        user=user
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# FAVORITES
# ============================================================

@app.route("/favorites")
def favorites():

    return render_template(
        "favorites.html"
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "GET":

        return render_template(
            "register.html"
        )

    username = request.form.get(
        "username",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

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

    password_hash = generate_password_hash(
        password
    )

    with AUTH_LOCK:

        workbook = _open_auth_workbook()

        users = workbook["users"]

        for row in users.iter_rows(
            min_row=2,
            values_only=True
        ):

            if (
                row[1] == username
                or str(row[2]).lower()
                == email
            ):

                workbook.close()

                return render_template(
                    "register.html",
                    error="Username or email already exists."
                )

        user_ids = [
            row[0]
            for row in users.iter_rows(
                min_row=2,
                values_only=True
            )
            if row[0]
        ]

        next_id = (
            max(user_ids, default=0)
            + 1
        )

        users.append([
            next_id,
            username,
            email,
            password_hash,
            int(time.time())
        ])

        _save_auth_workbook(
            workbook
        )

        workbook.close()

    return redirect(
        url_for("login")
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "GET":

        return render_template(
            "forgot_password.html"
        )

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    new_password = request.form.get(
        "password",
        ""
    )

    if len(new_password) < 8:

        return render_template(
            "forgot_password.html",
            error="Password must contain at least 8 characters."
        )

    password_hash = generate_password_hash(
        new_password
    )

    updated = False

    with AUTH_LOCK:

        workbook = _open_auth_workbook()

        users = workbook["users"]

        for row in users.iter_rows(
            min_row=2
        ):

            if (
                str(row[2].value).lower()
                == email
            ):

                row[3].value = password_hash

                updated = True

                break

        _save_auth_workbook(
            workbook
        )

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


# ============================================================
# HOME
# ============================================================

@app.route("/home")
def home():

    conn = get_db()

    total_restaurants = conn.execute(
        "SELECT COUNT(*) FROM restaurants"
    ).fetchone()[0]

    total_cities = conn.execute(
        "SELECT COUNT(DISTINCT City) FROM restaurants"
    ).fetchone()[0]

    avg_rating = conn.execute(
        "SELECT ROUND(AVG(Rating), 1) FROM restaurants"
    ).fetchone()[0]

    avg_cost = conn.execute(
        "SELECT ROUND(AVG(Cost), 0) FROM restaurants"
    ).fetchone()[0]

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

    city_data = [
        dict(row)
        for row in city_data
    ]

    if city_data:

        highest_city_total = city_data[0]["total"]

        for city in city_data:

            city["percentage"] = round(
                (
                    city["total"]
                    / highest_city_total
                ) * 100
            )

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

    cuisine_data = [
        dict(row)
        for row in cuisine_data
    ]

    if cuisine_data:

        highest_cuisine_total = (
            cuisine_data[0]["total"]
        )

        for cuisine in cuisine_data:

            cuisine["percentage"] = round(
                (
                    cuisine["total"]
                    / highest_cuisine_total
                ) * 100
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


# ============================================================
# NORMAL SEARCH
# ============================================================

@app.route("/search")
def search():

    keyword = request.args.get(
        "keyword",
        ""
    ).strip()

    city = request.args.get(
        "city",
        ""
    ).strip()

    cuisine = request.args.get(
        "cuisine",
        ""
    ).strip()

    max_cost = request.args.get(
        "max_cost",
        ""
    ).strip()

    min_rating = request.args.get(
        "min_rating",
        ""
    ).strip()

    conn = get_db()

    query = """
        SELECT *
        FROM restaurants
        WHERE 1=1
    """

    params = []

    if keyword:

        text = keyword.lower()

        cities = conn.execute(
            "SELECT DISTINCT City FROM restaurants"
        ).fetchall()

        found_city = None

        for row in cities:

            if (
                row["City"]
                and row["City"].lower()
                in text
            ):

                found_city = row["City"]

                break

        if found_city and not city:

            query += """
                AND City = ?
            """

            params.append(
                found_city
            )

        search_term = (
            text
            .replace("restaurants", "")
            .replace("restaurant", "")
            .replace(" in ", " ")
            .strip()
        )

        if search_term and not found_city:

            query += """
                AND (
                    Name LIKE ?
                    OR Cuisine LIKE ?
                    OR City LIKE ?
                    OR Location LIKE ?
                )
            """

            value = (
                "%"
                + search_term
                + "%"
            )

            params.extend([
                value,
                value,
                value,
                value
            ])

    if city:

        query += """
            AND City = ?
        """

        params.append(city)

    if cuisine:

        query += """
            AND Cuisine LIKE ?
        """

        params.append(
            "%"
            + cuisine
            + "%"
        )

    if max_cost:

        try:

            query += """
                AND Cost <= ?
            """

            params.append(
                float(max_cost)
            )

        except ValueError:
            pass

    if min_rating:

        try:

            query += """
                AND Rating >= ?
            """

            params.append(
                float(min_rating)
            )

        except ValueError:
            pass

    query += """
        ORDER BY Rating DESC
        LIMIT 60
    """

    restaurants = conn.execute(
        query,
        params
    ).fetchall()

    cities = conn.execute("""
        SELECT DISTINCT City
        FROM restaurants
        WHERE City IS NOT NULL
        AND City != ''
        ORDER BY City
    """).fetchall()

    cuisines_raw = conn.execute("""
        SELECT DISTINCT Cuisine
        FROM restaurants
        WHERE Cuisine IS NOT NULL
        AND Cuisine != ''
    """).fetchall()

    cuisine_set = set()

    for row in cuisines_raw:

        if row["Cuisine"]:

            for item in row["Cuisine"].split(","):

                c = item.strip()

                if c:
                    cuisine_set.add(c)

    sorted_cuisines = sorted(
        list(cuisine_set)
    )

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


# ============================================================
# AI SEARCH
# ============================================================

@app.route(
    "/ai-search",
    methods=["POST"]
)
def ai_search():

    user_query = request.form.get(
        "query",
        ""
    ).strip()

    if not user_query:

        return redirect(
            url_for("search")
        )

    prompt = f"""
Convert this restaurant request into JSON filters.

Request:
{user_query}

Return ONLY valid JSON.

Use exactly these fields:

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
- Do not add any explanation outside the JSON.
"""

    try:

        ai_text = ask_ai(
            prompt
        )

        # Remove possible markdown fences
        ai_text = ai_text.strip()

        if ai_text.startswith("```"):

            ai_text = (
                ai_text
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        filters = json.loads(
            ai_text
        )

    except Exception as error:

        print(
            "AI SEARCH ERROR:",
            error
        )

        return redirect(
            url_for(
                "search",
                keyword=user_query
            )
        )

    allowed_filters = [
        "keyword",
        "city",
        "cuisine",
        "max_cost",
        "min_rating"
    ]

    cleaned_filters = {
        key: filters.get(
            key,
            ""
        )
        for key in allowed_filters
        if filters.get(
            key,
            ""
        ) not in ("", None)
    }

    return redirect(
        url_for(
            "search",
            **cleaned_filters
        )
    )


# ============================================================
# RECOMMENDATION KEYWORDS
# ============================================================

MOOD_KEYWORDS = {

    "Comfort food": [
        "Biryani",
        "North Indian",
        "Fast Food",
        "Chinese"
    ],

    "Date night": [
        "Italian",
        "Continental",
        "Cafe"
    ],

    "Healthy": [
        "Healthy",
        "Salad",
        "Vegan",
        "Vegetarian"
    ],

    "Spicy": [
        "Indian",
        "Mexican",
        "Thai",
        "Biryani"
    ],

    "Quick bite": [
        "Fast Food",
        "Burger",
        "Pizza",
        "Street Food"
    ],

    "Sweet craving": [
        "Dessert",
        "Bakery",
        "Ice Cream",
        "Cafe"
    ],
}


MEAL_KEYWORDS = {

    "Breakfast": [
        "Breakfast",
        "Cafe",
        "Bakery"
    ],

    "Snacks": [
        "Fast Food",
        "Street Food",
        "Cafe"
    ],

    "Dinner": [
        "Dinner",
        "Fine Dining",
        "North Indian",
        "Chinese"
    ],
}


DIET_KEYWORDS = {

    "Vegetarian": [
        "Vegetarian",
        "South Indian",
        "North Indian",
        "Jain",
        "Pure Veg"
    ],

    "Vegan": [
        "Vegan",
        "Salad",
        "Health Food",
        "Juice"
    ],

    "Non-veg": [
        "Mughlai",
        "Kebab",
        "Tandoori",
        "Seafood",
        "Biryani",
        "Chicken",
        "Mutton",
        "Fish"
    ],
}


# ============================================================
# SMART RECOMMENDATIONS
# ============================================================

@app.route(
    "/recommendations",
    methods=["GET", "POST"]
)
@app.route(
    "/recommend",
    methods=["POST"]
)
def recommendations():

    preferences = {

        "city": request.form.get(
            "city",
            ""
        ).strip(),

        "mood": request.form.get(
            "mood",
            ""
        ).strip(),

        "meal": request.form.get(
            "meal",
            ""
        ).strip(),

        "cuisine": request.form.get(
            "cuisine",
            ""
        ).strip(),

        "diet": request.form.get(
            "diet",
            ""
        ).strip(),

        "max_cost": request.form.get(
            "max_cost",
            ""
        ).strip(),

        "min_rating": request.form.get(
            "min_rating",
            ""
        ).strip(),
    }

    if request.method == "GET":

        return render_template(
            "recommendations.html",
            preferences=preferences,
            restaurants=[],
            searched=False,
            ai_message=""
        )

    session["preferences"] = preferences

    conditions = [
        "1=1"
    ]

    params = []

    # --------------------------------------------------------
    # CITY
    # --------------------------------------------------------

    if preferences["city"]:

        conditions.append(
            "City LIKE ?"
        )

        params.append(
            "%"
            + preferences["city"]
            + "%"
        )

    # --------------------------------------------------------
    # CUISINE
    # --------------------------------------------------------

    if preferences["cuisine"]:

        conditions.append(
            "Cuisine LIKE ?"
        )

        params.append(
            "%"
            + preferences["cuisine"]
            + "%"
        )

    # --------------------------------------------------------
    # MOOD + MEAL
    # --------------------------------------------------------

    terms = []

    terms += MOOD_KEYWORDS.get(
        preferences["mood"],
        []
    )

    terms += MEAL_KEYWORDS.get(
        preferences["meal"],
        []
    )

    terms = list(
        dict.fromkeys(terms)
    )

    if terms:

        term_conditions = []

        for term in terms:

            term_conditions.append(
                """
                (
                    Cuisine LIKE ?
                    OR Name LIKE ?
                )
                """
            )

            params.extend([
                "%"
                + term
                + "%",

                "%"
                + term
                + "%"
            ])

        conditions.append(
            "("
            + " OR ".join(
                term_conditions
            )
            + ")"
        )

    # --------------------------------------------------------
    # DIET
    # --------------------------------------------------------

    if (
        preferences["diet"]
        and preferences["diet"]
        != "No preference"
    ):

        diet_terms = DIET_KEYWORDS.get(
            preferences["diet"],
            [
                preferences["diet"]
            ]
        )

        diet_conditions = []

        for term in diet_terms:

            diet_conditions.append(
                """
                (
                    Cuisine LIKE ?
                    OR Name LIKE ?
                )
                """
            )

            params.extend([
                "%"
                + term
                + "%",

                "%"
                + term
                + "%"
            ])

        conditions.append(
            "("
            + " OR ".join(
                diet_conditions
            )
            + ")"
        )

    # --------------------------------------------------------
    # MAX COST
    # --------------------------------------------------------

    try:

        if preferences["max_cost"]:

            conditions.append(
                "Cost <= ?"
            )

            params.append(
                float(
                    preferences["max_cost"]
                )
            )

    except ValueError:

        preferences["max_cost"] = ""

    # --------------------------------------------------------
    # MIN RATING
    # --------------------------------------------------------

    try:

        if preferences["min_rating"]:

            conditions.append(
                "Rating >= ?"
            )

            params.append(
                float(
                    preferences["min_rating"]
                )
            )

    except ValueError:

        preferences["min_rating"] = ""

    # --------------------------------------------------------
    # DATABASE QUERY
    # --------------------------------------------------------

    query = f"""
        SELECT
            Name,
            Location,
            City,
            Cuisine,
            Rating,
            Votes,
            Cost,
            "Google Maps Link"
        FROM restaurants
        WHERE {' AND '.join(conditions)}
        ORDER BY Rating DESC, Votes DESC
        LIMIT 12
    """

    conn = get_db()

    restaurants = [
        dict(row)
        for row in conn.execute(
            query,
            params
        ).fetchall()
    ]

    conn.close()

    # --------------------------------------------------------
    # AI EXPLANATIONS
    # --------------------------------------------------------

    reasons = {}

    if not restaurants:

        ai_message = (
            "No matches found. "
            "Try changing your preferences."
        )

    elif not OPENROUTER_API_KEY:

        ai_message = (
            "Showing database matches. "
            "AI is not configured."
        )

    else:

        prompt = f"""
You are the AI recommendation assistant for Restaurant Finder.

The user selected these preferences:

{json.dumps(preferences, indent=2)}

Here are the restaurants found by the database:

{json.dumps(restaurants[:6], indent=2)}

For EACH restaurant, write a very short reason explaining
why it matches the user's preferences.

Return ONLY valid JSON in exactly this format:

{{
    "reasons": [
        {{
            "name": "exact restaurant name",
            "reason": "short explanation"
        }}
    ]
}}

Rules:

- Use the exact restaurant name from the supplied data.
- Keep every reason under 20 words.
- Do not invent restaurant information.
- Do not add markdown.
- Do not add text outside the JSON.
"""

        try:

            ai_text = ask_ai(
                prompt
            )

            ai_text = ai_text.strip()

            # Remove markdown code fences if model adds them
            if ai_text.startswith("```"):

                ai_text = (
                    ai_text
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )

            result = json.loads(
                ai_text
            )

            reasons = {}

            for item in result.get(
                "reasons",
                []
            ):

                name = item.get(
                    "name"
                )

                reason = item.get(
                    "reason"
                )

                if name and reason:

                    reasons[name] = reason

            if reasons:

                ai_message = (
                    "✨ AI personalized "
                    "these recommendations for you."
                )

            else:

                ai_message = (
                    "✨ Restaurants matched "
                    "your selected preferences."
                )

        except Exception as error:

            print(
                "RECOMMENDATION AI ERROR:",
                error
            )

            reasons = {}

            ai_message = (
                "Showing database matches. "
                
            )

    # --------------------------------------------------------
    # ADD REASONS TO RESTAURANT CARDS
    # --------------------------------------------------------

    for restaurant in restaurants:

        restaurant["reason"] = reasons.get(
            restaurant["Name"],
            "Matches your selected preferences and restaurant rating."
        )

    # --------------------------------------------------------
    # RENDER PAGE
    # --------------------------------------------------------

    return render_template(
        "recommendations.html",
        preferences=preferences,
        restaurants=restaurants,
        searched=True,
        ai_message=ai_message,
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )