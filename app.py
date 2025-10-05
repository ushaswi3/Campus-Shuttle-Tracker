from flask import Flask, render_template, request, redirect, url_for, flash,session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase_client import supabase

app = Flask(__name__)
app.secret_key = "supersecret"  


# ------------------ Home ------------------
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/index")
def index():
    # Fetch buses, seats, and routes all at once
    buses = supabase.table("buses").select("*").execute().data
    seats = supabase.table("seats").select("*").execute().data
    routes = supabase.table("routes").select("*").execute().data

    # Map bus_id to seat availability
    seat_map = {s["bus_id"]: s["available_seats"] for s in seats}

    # Map bus_id to list of stops (routes)
    from collections import defaultdict
    route_map = defaultdict(list)
    for route in routes:
        route_map[route["bus_id"]].append((route["stop_time"], route["stop_name"]))

    # Sort stops by stop_time per bus and join to string
    for bus_id, stops in route_map.items():
        stops.sort(key=lambda x: x[0])  # Sort by stop_time
        route_map[bus_id] = " → ".join(stop[1] for stop in stops)

    # Prepare buses list with all needed info
    for bus in buses:
        bus["available_seats"] = seat_map.get(bus["bus_id"], bus["total_seats"])
        bus["route_info"] = route_map.get(bus["bus_id"], "Route not available")

    return render_template("index.html", buses=buses)

# ------------------ Booking ------------------

@app.route("/book", methods=["GET", "POST"])
def book():
    buses = supabase.table("buses").select("*").execute().data
    routes = supabase.table("routes").select("*").execute().data

    # Build mapping from bus_id to route string
    from collections import defaultdict
    route_map = defaultdict(list)
    for route in routes:
        route_map[route["bus_id"]].append((route["stop_time"], route["stop_name"]))
    for bus_id in route_map:
        # Sort stops in time order and join names
        route_map[bus_id].sort(key=lambda x: x[0])
        route_map[bus_id] = " → ".join(stop[1] for stop in route_map[bus_id])

    # Attach route_info to each bus
    for bus in buses:
        bus["route_info"] = route_map.get(bus["bus_id"], "Route: N/A")

    if request.method == "POST":
        bus_id = int(request.form["bus_id"])
        user_name = request.form["user_name"]

        # Check availability
        seat_info = supabase.table("seats").select("*").eq("bus_id", bus_id).execute().data
        if not seat_info or seat_info[0]["available_seats"] <= 0:
            flash("No seats available for this bus!", "danger")
            return redirect(url_for("index"))

        supabase.table("occupancy").insert({
            "bus_id": bus_id,
            "user_name": user_name
        }).execute()

        supabase.table("seats").update({
            "available_seats": seat_info[0]["available_seats"] - 1
        }).eq("bus_id", bus_id).execute()

        flash("Booking confirmed!", "success")
        return redirect(url_for("bus_summary"))

    # Pass enhanced buses list to the template
    return render_template("book.html", buses=buses)


# ------------------ Bus Schedule ------------------

@app.route("/schedule/<int:bus_id>")
def schedule(bus_id):
    routes = supabase.table("routes").select("*").eq("bus_id", bus_id).order("stop_time").execute().data
    bus = supabase.table("buses").select("*").eq("bus_id", bus_id).single().execute().data
    print("Bus ID:", bus_id)
    print("Routes:", routes)
    print("Bus:", bus)
    return render_template("schedule.html", routes=routes, bus=bus)



# ------------------ Intent to Travel ------------------
@app.route("/intent", methods=["GET", "POST"])
def intent():
    buses = supabase.table("buses").select("*").execute().data

    if request.method == "POST":
        student_id = request.form["student_id"]
        bus_id = int(request.form["bus_id"])

        supabase.table("intent_to_travel").insert({
            "student_id": student_id,
            "bus_id": bus_id,
            "seat_reserved": False
        }).execute()

        flash("Your travel intent has been recorded!", "success")
        return redirect(url_for("bus_summary"))

    return render_template("intent.html", buses=buses)


# ------------------------
# Admin Registration & Login
# ------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if password != confirm:
            flash("Passwords do not match!", "danger")
            return redirect(url_for("register"))

        # Check if username already exists
        existing = supabase.table("admins").select("*").eq("username", username).execute().data
        if existing:
            flash("Username already taken!", "danger")
            return redirect(url_for("register"))

        # Hash password
        hashed_pw = generate_password_hash(password)

        # Insert admin
        supabase.table("admins").insert({
            "username": username,
            "password": hashed_pw
        }).execute()

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        result = supabase.table("admins").select("*").eq("username", username).execute()
        admin = result.data[0] if result.data else None

        if admin and check_password_hash(admin["password"], password):
            session["admin"] = admin["username"]
            flash("Login successful!", "success")
            return redirect(url_for("admin"))
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    flash("Logged out successfully", "info")
    return redirect(url_for("login"))


# ------------------------
# Admin Dashboard 
# ------------------------
from functools import wraps
from flask import session, flash, redirect, url_for, render_template

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin" not in session:
            flash("You must log in first", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/admin")
@admin_required
def admin():
    # Fetch bus details
    buses_response = supabase.table("buses").select("*").execute()
    buses = buses_response.data if buses_response.data else []

    # Fetch seat info
    seats_response = supabase.table("seats").select("*").execute()
    seats = seats_response.data if seats_response.data else []

    # Fetch intent-to-travel data
    intents_response = supabase.table("intent_to_travel").select("*").execute()
    intents = intents_response.data if intents_response.data else []

    # Merge buses and seat info 
    bus_details = []
    for bus in buses:
        seat_info = next((s for s in seats if s["bus_id"] == bus["bus_id"]), None)
        bus_details.append({
            "bus_id": bus["bus_id"],
            "bus_number": bus["bus_number"],
            "total_seats": bus["total_seats"],
            "available_seats": seat_info["available_seats"] if seat_info else bus["total_seats"]
        })

    # Render the dashboard template with merged data
    return render_template("admin.html", buses=bus_details, intents=intents)



# -------------- Bus Summary --------------
from collections import defaultdict
from datetime import datetime
from flask import render_template

@app.route("/bus_summary")
def bus_summary():
    # fetch (guard against None)
    buses = supabase.table("buses").select("*").execute().data or []
    seats = supabase.table("seats").select("*").execute().data or []
    routes = supabase.table("routes").select("*").execute().data or []
    intents = supabase.table("intent_to_travel").select("*").execute().data or []

    # seat map: bus_id -> available_seats (int)
    seat_map = {}
    for s in seats:
        try:
            seat_map[s.get("bus_id")] = int(s.get("available_seats") or 0)
        except Exception:
            seat_map[s.get("bus_id")] = 0

    # route_map: bus_id -> list of {stop_time, stop_name, sort_key}
    route_map = defaultdict(list)
    for r in routes:
        bus_id = r.get("bus_id")
        if bus_id is None:
            continue
        stop_time = r.get("stop_time")
        sort_key = None
        # try parse stop_time strings like "HH:MM" or "HH:MM:SS"
        if isinstance(stop_time, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    sort_key = datetime.strptime(stop_time, fmt).time()
                    break
                except Exception:
                    sort_key = stop_time  # fallback: keep original string
        else:
            sort_key = stop_time
        route_map[bus_id].append({
            "stop_time": stop_time,
            "stop_name": r.get("stop_name") or "",
            "sort_key": sort_key
        })

    # intent counts
    intent_count = defaultdict(int)
    for it in intents:
        if it.get("bus_id") is not None:
            intent_count[it.get("bus_id")] += 1

    # build cards list (precompute percent & progress class to keep template simple)
    cards = []
    for bus in buses:
        bus_id = bus.get("bus_id")
        if bus_id is None:
            continue

        stops = route_map.get(bus_id, [])
        # sort safely: place None at the end
        try:
            stops_sorted = sorted(stops, key=lambda x: (x["sort_key"] is None, x["sort_key"]))
        except Exception:
            stops_sorted = stops

        schedule_str = " → ".join([s["stop_name"] for s in stops_sorted if s.get("stop_name")]) or "No route info"
        next_stop = stops_sorted[0]["stop_name"] if stops_sorted else "N/A"
        next_time = stops_sorted[0]["stop_time"] if stops_sorted else "N/A"

        try:
            total_seats = int(bus.get("total_seats") or 0)
        except Exception:
            total_seats = 0
        available_seats = int(seat_map.get(bus_id, 0))
        intents_num = int(intent_count.get(bus_id, 0))

        # percent & progress class (avoid division by zero)
        if total_seats > 0:
            percent = int((available_seats / total_seats) * 100)
            ratio = available_seats / total_seats
        else:
            percent = 0
            ratio = 0.0

        if total_seats > 0 and available_seats == total_seats:
            progress_class = "bg-success"
        elif ratio < 0.3:
            progress_class = "bg-danger"
        else:
            progress_class = "bg-warning"

        cards.append({
            "bus_number": bus.get("bus_number") or bus.get("bus_name") or "N/A",
            "bus_id": bus_id,
            "route": schedule_str,
            "next_stop": next_stop,
            "next_time": next_time,
            "available_seats": available_seats,
            "total_seats": total_seats,
            "intent_count": intents_num,
            "percent": percent,
            "progress_class": progress_class
        })

    # debug print (remove when stable)
    print("bus_summary cards:", cards)
    return render_template("bus_summary.html", cards=cards)

#------------------------------------------

@app.route("/edit_bus_full/<int:bus_id>", methods=["GET", "POST"])
@admin_required
def edit_bus_full(bus_id):
    # Fetch bus, seat, routes
    bus = supabase.table("buses").select("*").eq("bus_id", bus_id).single().execute().data
    seat = supabase.table("seats").select("*").eq("bus_id", bus_id).single().execute().data
    routes = supabase.table("routes").select("*").eq("bus_id", bus_id).order("stop_time").execute().data

    if request.method == "POST":
        # --- Update bus ---
        bus_number = request.form["bus_number"]
        total_seats = int(request.form["total_seats"])
        supabase.table("buses").update({"bus_number": bus_number, "total_seats": total_seats}).eq("bus_id", bus_id).execute()

        # --- Update seats ---
        available_seats = int(request.form["available_seats"])
        supabase.table("seats").update({"available_seats": available_seats}).eq("bus_id", bus_id).execute()

        # --- Update existing routes ---
        for r in routes:
            stop_name = request.form.get(f"stop_name_{r['route_id']}")
            stop_time = request.form.get(f"stop_time_{r['route_id']}")
            if stop_name and stop_time:
                supabase.table("routes").update({
                    "stop_name": stop_name,
                    "stop_time": stop_time
                }).eq("route_id", r["route_id"]).execute()

        # --- Add new routes ---
        new_stops = request.form.getlist("new_stop_name[]")
        new_times = request.form.getlist("new_stop_time[]")
        for name, time in zip(new_stops, new_times):
            if name.strip() and time.strip():
                supabase.table("routes").insert({
                    "bus_id": bus_id,
                    "stop_name": name,
                    "stop_time": time
                }).execute()

        # --- Delete routes ---
        delete_ids = request.form.getlist("delete_route[]")
        for rid in delete_ids:
            supabase.table("routes").delete().eq("route_id", int(rid)).execute()

        flash("Bus details updated successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("edit_bus_full.html", bus=bus, seat=seat, routes=routes)

# ------------------ Run ------------------
if __name__ == "__main__":
    app.run(debug=True)
