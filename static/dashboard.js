// Comportamiento del dashboard: pestañas, actualización automática,
// botones de las órdenes e interruptor de disponibilidad de los productos.

(function () {
  'use strict';

  const REFRESH_MS = 15000;   // la pestaña Pedidos se actualiza cada 15 s mientras está a la vista
  const PESTANAS = ['pedidos', 'productos', 'agregar'];
  const PANELES = {           // pestañas que se piden de nuevo al servidor
    pedidos: '/dashboard/panel/orders',
    productos: '/dashboard/panel/products',
  };

  const botones = document.querySelectorAll('.pestanas button');
  const ultimoHTML = {};      // último contenido recibido, para no redibujar si no cambió
  let activa = 'pedidos';

  function irALogin() {
    window.location.href = '/login';
  }

  // ---------- Pestañas ----------

  function mostrarPestana(nombre, recargar) {
    if (!PESTANAS.includes(nombre)) nombre = 'pedidos';
    activa = nombre;
    document.querySelectorAll('.tab').forEach(function (t) {
      t.classList.toggle('activa', t.id === nombre);
    });
    botones.forEach(function (b) {
      b.classList.toggle('activa', b.dataset.tab === nombre);
    });
    history.replaceState(null, '', '#' + nombre);
    if (recargar && PANELES[nombre]) refrescar(nombre);
  }

  botones.forEach(function (b) {
    b.addEventListener('click', function () {
      mostrarPestana(b.dataset.tab, true);   // al activarse una pestaña se actualiza
    });
  });

  // ---------- Actualización ----------

  async function refrescar(nombre) {
    try {
      const r = await fetch(PANELES[nombre], { credentials: 'same-origin' });
      if (r.status === 401) { irALogin(); return; }
      if (!r.ok) return;
      const html = await r.text();
      if (html === ultimoHTML[nombre]) return;
      ultimoHTML[nombre] = html;
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      if (tmp.firstElementChild) {
        document.getElementById(nombre).innerHTML = tmp.firstElementChild.innerHTML;
      }
    } catch (err) {
      // sin conexión: se deja en pantalla lo que ya había
    }
  }

  setInterval(function () {
    if (activa === 'pedidos' && !document.hidden) refrescar('pedidos');
  }, REFRESH_MS);

  // Al volver a esta pestaña del navegador también se actualiza
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && PANELES[activa]) refrescar(activa);
  });

  // ---------- Órdenes: Descartar / Realizado ----------

  document.addEventListener('click', async function (e) {
    const boton = e.target.closest('.orden [data-accion]');
    if (!boton) return;

    const orden = boton.closest('.orden');
    const accion = boton.dataset.accion;   // "descartado" o "realizado"
    if (accion === 'descartado' &&
        !confirm('¿Descartar esta orden? Se devolverán los puntos al usuario.')) {
      return;
    }

    const botonesOrden = orden.querySelectorAll('button');
    botonesOrden.forEach(function (b) { b.disabled = true; });

    let guardado = false;
    try {
      const r = await fetch('/dashboard/orders/' + orden.dataset.orderId + '/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: accion }),
      });
      if (r.status === 401) { irALogin(); return; }
      guardado = r.ok;
    } catch (err) {
      // sin conexión
    }

    if (!guardado) botonesOrden.forEach(function (b) { b.disabled = false; });
    refrescar('pedidos');
  });

  // ---------- Productos: interruptor de disponibilidad ----------

  document.addEventListener('change', async function (e) {
    const interruptor = e.target.closest('.producto [data-accion="disponibilidad"]');
    if (!interruptor) return;

    const fila = interruptor.closest('.producto');
    const disponible = interruptor.checked;
    try {
      const r = await fetch('/dashboard/products/' + fila.dataset.productId + '/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: disponible }),
      });
      if (r.status === 401) { irALogin(); return; }
      if (!r.ok) throw new Error('no guardado');
      fila.classList.toggle('inactivo', !disponible);
    } catch (err) {
      interruptor.checked = !disponible;   // no se pudo guardar: vuelve a como estaba
    }
  });

  // ---------- Inicio ----------

  // El servidor ya mandó los datos actuales, así que al cargar no hace falta pedirlos otra vez.
  mostrarPestana(window.location.hash.slice(1), false);
})();
