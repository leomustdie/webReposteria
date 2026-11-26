from flask import Flask, render_template, request, redirect, url_for, session, abort

app = Flask(__name__)
app.secret_key = 'unicorniovoladordetrescabezasconunperromontado'

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
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', usuario=session['usuario'])

if __name__ == '__main__':
    print("Servidor corriendo en: http://127.0.0.1:5000/home")
    app.run(debug=True)