import os
import sqlite3

from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cafeteria.db")

STARTING_BALANCE = 250

# Order states
ORDER_PENDING = "pendiente"
ORDER_DONE = "realizado"
ORDER_DISCARDED = "descartado"

# Same limit as the app's ( - n + ) stepper
MAX_OPTION_QUANTITY = 5

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
            total     INTEGER NOT NULL,
            notes     TEXT
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

    # Databases created before the overall order note existed get the new column
    order_columns = [row["name"] for row in conn.execute("PRAGMA table_info(orders)")]
    if "notes" not in order_columns:
        conn.execute("ALTER TABLE orders ADD COLUMN notes TEXT")

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


# ---------- Dashboard: products tab ----------

def get_all_products():
    """Every product (active or not) for the Productos tab."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT product_id, product_name, description, price, photo, status
           FROM product ORDER BY product_id"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_product_status(product_id, active):
    """Turns a product on (True) or off (False). Returns False if it doesn't exist."""
    conn = get_connection()
    cur = conn.execute("UPDATE product SET status = ? WHERE product_id = ?",
                       (1 if active else 0, product_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ---------- Orders ----------

class OrderError(Exception):
    """Raised when an order can't be saved. Carries the HTTP status and the message for the app."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def create_order(username, notes, items):
    """Saves an order sent by the app and takes its total from the user's balance.

    items = [{"id": product_id, "quantity": n, "options": [{"id": option_id, "quantity": n}]}]

    Prices are always read from the database, never from the app.
    Returns {"order_id", "total", "balance"} or raises OrderError.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")  # locks the db so two orders can't spend the same points

        user = conn.execute("SELECT matricula, balance FROM users WHERE username = ?",
                            (username,)).fetchone()
        if user is None:
            raise OrderError(401, "Usuario no encontrado")

        lines = []  # (product_id, unit_price, quantity, [(option_id, quantity), ...])
        total = 0
        for item in items:
            product = conn.execute(
                "SELECT product_name, price, status FROM product WHERE product_id = ?",
                (item["id"],)).fetchone()
            if product is None:
                raise OrderError(400, "Uno de los productos no existe")
            if not product["status"]:
                raise OrderError(409, product["product_name"] + " ya no está disponible")

            unit_price = product["price"]
            chosen = []
            used_options = set()
            used_single_groups = set()
            for opt in item["options"]:
                row = conn.execute(
                    """SELECT o.* FROM options o
                       JOIN product_options po ON po.option_id = o.option_id
                       WHERE po.product_id = ? AND o.option_id = ?""",
                    (item["id"], opt["id"])).fetchone()
                if row is None:
                    raise OrderError(400, "Opción no válida para " + product["product_name"])
                if row["option_id"] in used_options:
                    raise OrderError(400, "Opción repetida en " + product["product_name"])
                used_options.add(row["option_id"])

                if row["option_type"] == "quantity":
                    if not 1 <= opt["quantity"] <= MAX_OPTION_QUANTITY:
                        raise OrderError(400, "Cantidad no válida para " + row["option_name"])
                else:
                    if opt["quantity"] != 1:
                        raise OrderError(400, "Cantidad no válida para " + row["option_name"])
                if row["option_type"] == "single":
                    if row["group_name"] in used_single_groups:
                        raise OrderError(400, "Solo puedes elegir una opción de " + row["group_name"])
                    used_single_groups.add(row["group_name"])

                unit_price += row["extra_price"] * opt["quantity"]
                chosen.append((row["option_id"], opt["quantity"]))

            lines.append((item["id"], unit_price, item["quantity"], chosen))
            total += unit_price * item["quantity"]

        if user["balance"] < total:
            raise OrderError(409, "Saldo insuficiente")

        cur = conn.execute(
            "INSERT INTO orders (matricula, status, total, notes) VALUES (?, ?, ?, ?)",
            (user["matricula"], ORDER_PENDING, total, notes))
        order_id = cur.lastrowid
        for product_id, unit_price, quantity, chosen in lines:
            cur = conn.execute(
                """INSERT INTO order_details (order_id, product_id, unit_price, quantity)
                   VALUES (?, ?, ?, ?)""",
                (order_id, product_id, unit_price, quantity))
            conn.executemany(
                """INSERT INTO order_item_options (order_detail_id, option_id, quantity)
                   VALUES (?, ?, ?)""",
                [(cur.lastrowid, option_id, qty) for option_id, qty in chosen])
        conn.execute("UPDATE users SET balance = balance - ? WHERE matricula = ?",
                     (total, user["matricula"]))
        conn.commit()
        return {"order_id": order_id, "total": total, "balance": user["balance"] - total}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_orders():
    """Pending orders for the Pedidos tab, lowest id first, ready for the template.

    The options of each product come as one line, e.g. "Tamaño: Chico, Sabor: Vainilla".
    """
    conn = get_connection()
    orders = conn.execute(
        """SELECT o.order_id, u.username, o.notes, o.total
           FROM orders o JOIN users u ON u.matricula = o.matricula
           WHERE o.status = ?
           ORDER BY o.order_id ASC""",
        (ORDER_PENDING,)).fetchall()

    result = []
    for o in orders:
        details = conn.execute(
            """SELECT d.order_detail_id, d.quantity, p.product_name
               FROM order_details d JOIN product p ON p.product_id = d.product_id
               WHERE d.order_id = ? ORDER BY d.order_detail_id""",
            (o["order_id"],)).fetchall()

        items = []
        for d in details:
            chosen = conn.execute(
                """SELECT op.option_name, op.option_type, op.group_name, i.quantity
                   FROM order_item_options i JOIN options op ON op.option_id = i.option_id
                   WHERE i.order_detail_id = ? ORDER BY op.option_id""",
                (d["order_detail_id"],)).fetchall()

            groups = {}  # group name -> chosen options, in order
            for c in chosen:
                text = c["option_name"]
                if c["option_type"] == "quantity" and c["quantity"] > 1:
                    text += " ×" + str(c["quantity"])
                groups.setdefault(c["group_name"], []).append(text)

            items.append({
                "name": d["product_name"],
                "quantity": d["quantity"],
                "options_text": ", ".join(g + ": " + " + ".join(texts) for g, texts in groups.items()),
            })

        result.append({
            "order_id": o["order_id"],
            "username": o["username"],
            "notes": o["notes"],
            "total": o["total"],
            "products": items,
        })
    conn.close()
    return result


def set_order_status(order_id, new_status):
    """Moves a pending order to done or discarded. Discarding gives the points back.

    Returns True if the order changed, False if it doesn't exist or was already handled.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT matricula, total, status FROM orders WHERE order_id = ?",
                             (order_id,)).fetchone()
        if order is None or order["status"] != ORDER_PENDING:
            conn.rollback()
            return False
        conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new_status, order_id))
        if new_status == ORDER_DISCARDED:
            conn.execute("UPDATE users SET balance = balance + ? WHERE matricula = ?",
                         (order["total"], order["matricula"]))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
