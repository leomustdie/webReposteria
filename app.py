import os
import re
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify, flash
from werkzeug.utils import secure_filename

import database

app = Flask(__name__)
app.secret_key = 'unicorniovoladordetrescabezasconunperromontado'

database.init_db()

PHOTO_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

BD_Empleados = {
    "derek": {"password": "contraseña"},
    "leonel": {"password": "52837"}
}

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')

        if usuario in BD_Empleados and BD_Empleados[usuario]["password"] == password:
            session['usuario'] = usuario
            return redirect(url_for('dashboard'))
        else: 
            return render_template('login.html', error="Usuario o contraseña incorrecta")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', usuario=session['usuario'],
                           orders=database.get_pending_orders(),
                           products=database.get_all_products(),
                           categories=database.get_categories(),
                           option_groups=database.get_option_groups())

# ---------- Dashboard: pieces the page reloads by itself ----------

@app.route('/dashboard/panel/orders')
def dashboard_panel_orders():
    if 'usuario' not in session:
        abort(401)
    return render_template('orders_panel.html', orders=database.get_pending_orders())

@app.route('/dashboard/panel/products')
def dashboard_panel_products():
    if 'usuario' not in session:
        abort(401)
    return render_template('products_panel.html', products=database.get_all_products())

@app.route('/dashboard/orders/<int:order_id>/status', methods=['POST'])
def dashboard_order_status(order_id):
    if 'usuario' not in session:
        abort(401)
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in (database.ORDER_DONE, database.ORDER_DISCARDED):
        abort(400)
    if not database.set_order_status(order_id, new_status):
        return jsonify(success=False), 409  # doesn't exist or was already handled
    return jsonify(success=True)

@app.route('/dashboard/products/<int:product_id>/status', methods=['POST'])
def dashboard_product_status(product_id):
    if 'usuario' not in session:
        abort(401)
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('active'), bool):
        abort(400)
    if not database.set_product_status(product_id, data['active']):
        abort(404)
    return jsonify(success=True)

@app.route('/dashboard/products', methods=['POST'])
def dashboard_add_product():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    try:
        product_name = request.form['product_name'].strip()
        description = request.form.get('description', '').strip()
        price = int(request.form['price'])
        making_time = int(request.form['making_time'])
        category_id = int(request.form['category_id'])
        option_ids = [int(i) for i in request.form.getlist('option_ids')]
    except (KeyError, ValueError):
        abort(400)
    if not product_name or price < 0 or making_time < 0:
        abort(400)

    photo_file = request.files.get('photo')
    photo = None
    if photo_file and photo_file.filename:
        ext = os.path.splitext(secure_filename(photo_file.filename))[1].lower()
        if ext not in PHOTO_EXTENSIONS:
            abort(400)
        photo = 'products/' + uuid.uuid4().hex + ext

    product_id = database.add_product(product_name, description, price, making_time,
                                      photo, category_id, option_ids)
    if product_id is None:
        abort(400)

    if photo:
        folder = os.path.join(app.static_folder, 'products')
        os.makedirs(folder, exist_ok=True)
        photo_file.save(os.path.join(app.static_folder, photo))

    flash("Producto agregado correctamente")
    return redirect(url_for('dashboard') + '#productos')

# ---------- API for the cafeteria app ----------

@app.route('/api/products')
def api_products():
    products = database.get_active_products()
    for p in products:
        if p['photo']:
            p['photo'] = url_for('static', filename=p['photo'], _external=True)
    return jsonify({"products": products})

def valid_matricula(matricula):
    if not re.fullmatch(r'\d{6}', matricula):
        return False
    return int(matricula[:2]) <= datetime.now().year % 100

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    matricula = str(data.get('matricula', '')).strip()
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))

    if not valid_matricula(matricula):
        return jsonify(success=False, message="Matrícula inválida"), 400
    if not username or not password:
        return jsonify(success=False, message="Usuario y contraseña son obligatorios"), 400

    error = database.create_user(matricula, username, password)
    if error == "matricula":
        return jsonify(success=False, message="Esta matrícula ya tiene una cuenta"), 409
    if error == "username":
        return jsonify(success=False, message="Ese nombre de usuario ya existe"), 409
    return jsonify(success=True, message="Cuenta creada"), 201

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))

    if database.check_user(username, password):
        return jsonify(success=True, message="Bienvenido")
    return jsonify(success=False, message="Usuario o contraseña incorrecta"), 401

def read_order(data):
    """Reads the order the app sends back. Only ids and quantities are used.

    The app can send the menu JSON trimmed down to what the user chose, adding a
    "quantity" to each product (and to each choice of a "quantity" option):
    {"username": "ana", "notes": "...",
     "items": [{"id": 1, "quantity": 2,
                "options": [{"group": "Extras", "type": "quantity",
                             "choices": [{"id": 15, "quantity": 2}]}]}]}
    Raises ValueError/KeyError/TypeError/AttributeError if something is malformed.
    """
    username = str(data['username']).strip()
    notes = str(data.get('notes') or '').strip()[:200]

    items = []
    for item in data['items']:
        options = []
        for group in item.get('options') or []:
            for choice in group['choices']:
                options.append({"id": int(choice['id']), "quantity": int(choice.get('quantity', 1))})
        quantity = int(item.get('quantity', 1))
        if quantity < 1:
            raise ValueError("quantity")
        items.append({"id": int(item['id']), "quantity": quantity, "options": options})

    if not username or not items:
        raise ValueError("empty")
    return username, notes, items

@app.route('/api/orders', methods=['POST'])
def api_orders():
    data = request.get_json(silent=True) or {}
    try:
        username, notes, items = read_order(data)
    except (KeyError, TypeError, ValueError, AttributeError):
        return jsonify(success=False, message="Pedido inválido"), 400

    try:
        result = database.create_order(username, notes, items)
    except database.OrderError as e:
        return jsonify(success=False, message=e.message), e.status
    return jsonify(success=True, message="Pedido recibido", **result), 201

if __name__ == '__main__':
    print("Servidor corriendo en: http://127.0.0.1:5000/home")
    app.run(host='0.0.0.0', port=5000, debug=True)