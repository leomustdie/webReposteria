import os
import sqlite3

from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cafeteria.db")

STARTING_BALANCE = 250

# Static values (loaded only when the tables are empty)
CATEGORIES = ["Bebida", "Postre"]

# (option_name, option_type, group_name, extra_price)
OPTIONS = [
    ("Chico", "single", "Tamaño", 0),
    ("Mediano", "single", "Tamaño", 15),
    ("Grande", "single", "Tamaño", 10),
    ("Jumbo", "single", "Tamaño", 5),
    ("Moka", "single", "Sabor", 0),
    ("Vainilla", "single", "Sabor", 0),
    ("Chocolate", "single", "Sabor", 0),
    ("Fresa", "single", "Sabor", 0),
    ("Caramelo", "single", "Sabor", 0),
    ("Canela", "multi", "Toppings", 5),
    ("Chispas de chocolate", "multi", "Toppings", 5),
    ("Crema batida", "multi", "Toppings", 8),
    ("Caramelo", "multi", "Toppings", 5),
    ("Galleta", "multi", "Toppings", 8),
    ("Extra shot", "quantity", "Extras", 5),
    ("Azúcar", "quantity", "Extras", 2),
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            matricula TEXT PRIMARY KEY,
            username  TEXT NOT NULL UNIQUE,
            password  TEXT NOT NULL,
            balance   INTEGER NOT NULL DEFAULT 250
        );

        CREATE TABLE IF NOT EXISTS category (
            category_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS product (
            product_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            description  TEXT,
            price        INTEGER NOT NULL,
            making_time  INTEGER NOT NULL,
            photo        TEXT,
            category_id  INTEGER NOT NULL REFERENCES category(category_id),
            status       INTEGER NOT NULL DEFAULT 1 CHECK (status IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS options (
            option_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            option_name TEXT NOT NULL,
            option_type TEXT NOT NULL CHECK (option_type IN ('single', 'multi', 'quantity')),
            group_name  TEXT NOT NULL,
            extra_price INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS product_options (
            product_id INTEGER NOT NULL REFERENCES product(product_id),
            option_id  INTEGER NOT NULL REFERENCES options(option_id),
            PRIMARY KEY (product_id, option_id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            matricula TEXT NOT NULL REFERENCES users(matricula),
            status    TEXT NOT NULL,
            total     INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_details (
            order_detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id        INTEGER NOT NULL REFERENCES orders(order_id),
            product_id      INTEGER NOT NULL REFERENCES product(product_id),
            unit_price      INTEGER NOT NULL,
            quantity        INTEGER NOT NULL,
            notes           TEXT
        );

        CREATE TABLE IF NOT EXISTS order_item_options (
            order_detail_id INTEGER NOT NULL REFERENCES order_details(order_detail_id),
            option_id       INTEGER NOT NULL REFERENCES options(option_id),
            quantity        INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (order_detail_id, option_id)
        );
    """)

    if conn.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 0:
        conn.executemany("INSERT INTO category (category_name) VALUES (?)",
                         [(name,) for name in CATEGORIES])

    if conn.execute("SELECT COUNT(*) FROM options").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO options (option_name, option_type, group_name, extra_price) VALUES (?, ?, ?, ?)",
            OPTIONS)

    conn.commit()
    conn.close()


# ---------- Dashboard: form data ----------

def get_categories():
    conn = get_connection()
    rows = conn.execute("SELECT category_id, category_name FROM category ORDER BY category_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _group_options(rows):
    """Groups option rows by group_name, keeping the order they appear in."""
    groups = []
    by_name = {}
    for r in rows:
        if r["group_name"] not in by_name:
            group = {"group": r["group_name"], "type": r["option_type"], "choices": []}
            by_name[r["group_name"]] = group
            groups.append(group)
        by_name[r["group_name"]]["choices"].append(
            {"id": r["option_id"], "name": r["option_name"], "extra_price": r["extra_price"]})
    return groups


def get_option_groups():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM options ORDER BY option_id").fetchall()
    conn.close()
    return _group_options(rows)


# ---------- Dashboard: add product ----------

def add_product(product_name, description, price, making_time, photo, category_id, option_ids):
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO product (product_name, description, price, making_time, photo, category_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (product_name, description, price, making_time, photo, category_id))
        product_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO product_options (product_id, option_id) VALUES (?, ?)",
            [(product_id, option_id) for option_id in option_ids])
        conn.commit()
        return product_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


# ---------- API: products ----------

def get_active_products():
    """Active products (status = 1) with their options, ready to become JSON."""
    conn = get_connection()
    products = conn.execute(
        """SELECT p.product_id, p.product_name, p.description, p.price, p.making_time,
                  p.photo, c.category_name
           FROM product p JOIN category c ON c.category_id = p.category_id
           WHERE p.status = 1
           ORDER BY p.product_id"""
    ).fetchall()

    result = []
    for p in products:
        option_rows = conn.execute(
            """SELECT o.* FROM options o
               JOIN product_options po ON po.option_id = o.option_id
               WHERE po.product_id = ?
               ORDER BY o.option_id""",
            (p["product_id"],)).fetchall()
        result.append({
            "id": p["product_id"],
            "name": p["product_name"],
            "description": p["description"],
            "price": p["price"],
            "making_time": p["making_time"],
            "photo": p["photo"],
            "category": p["category_name"],
            "options": _group_options(option_rows),
        })
    conn.close()
    return result


# ---------- API: users ----------

def create_user(matricula, username, password):
    """Returns None on success, or "matricula" / "username" if that value already exists."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (matricula, username, password, balance) VALUES (?, ?, ?, ?)",
            (matricula, username, generate_password_hash(password), STARTING_BALANCE))
        conn.commit()
        return None
    except sqlite3.IntegrityError as e:
        conn.rollback()
        return "matricula" if "matricula" in str(e) else "username"
    finally:
        conn.close()


def check_user(username, password):
    """True if the username exists and the password matches."""
    conn = get_connection()
    row = conn.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row is not None and check_password_hash(row["password"], password)
