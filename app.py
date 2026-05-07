import os
import tempfile
from flask import Flask, render_template, request, send_file, redirect, flash, jsonify, session
import requests
from bs4 import BeautifulSoup
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
# --- SE AGREGARON SimpleDocTemplate y Spacer PARA LA TABLA INTELIGENTE ---
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.units import cm
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "clave_secreta_para_crest_santa_ana" # Necesario para mensajes flash
RUTA_EXCEL = "proveedores.xlsx"
CREADOR = "Desarrollado por: Jonathan Gómez"
ARCHIVO_COOKIE = "cookie_cache.txt"

# --- UTILIDADES DE SESIÓN ---

def obtener_cookie_guardada():
    """Lee la cookie del archivo de texto si existe."""
    if os.path.exists(ARCHIVO_COOKIE):
        with open(ARCHIVO_COOKIE, "r") as f:
            return f.read().strip()
    return None

# --- LÓGICA DE NEGOCIO (EXCEL Y WEB) ---

def obtener_proveedor(modelo_equipo):
    """Busca el proveedor en el Excel basado en el modelo."""
    try:
        if not os.path.exists(RUTA_EXCEL): return "EXCEL NO ENCONTRADO"
        df = pd.read_excel(RUTA_EXCEL, dtype=str)
        # Ajustamos índices de columnas según tu Excel: 3 es Proveedor, 5 es Modelo
        col_prov, col_mod = df.columns[3], df.columns[5]
        
        modelo_buscar = str(modelo_equipo).strip().upper()
        df[col_mod] = df[col_mod].astype(str).str.strip().str.upper()
        
        # Búsqueda parcial (contiene el modelo)
        match = df[df[col_mod].str.contains(modelo_buscar, na=False, regex=False)]
        
        if not match.empty:
            return str(match.iloc[0][col_prov]).strip()
        return "PROVEEDOR NO ENCONTRADO"
    except Exception as e:
        print(f"Error leyendo Excel: {e}")
        return "ERROR EXCEL"

def extraer_datos_web(ticket_id):
    """Descarga los datos del ticket usando la sesión guardada."""
    cookie_valor = obtener_cookie_guardada()
    if not cookie_valor:
        return "NO_COOKIE"

    url = f"https://soporte-crest.mined.gob.sv/soportev2/ticket/mostrar/{ticket_id}/ESTUDIANTE"
    cookies = {'ci_session_stv2': cookie_valor}
    
    try:
        r = requests.get(url, cookies=cookies, timeout=10)
        
        if r.status_code == 404:
            return "ERROR_NA"
            
        # Si redirige al login o da error de sesión
        if "Iniciar sesión" in r.text:
            return "ERROR_SESION"
            
        if r.status_code != 200:
            return "ERROR_NA"
        
        soup = BeautifulSoup(r.text, 'html.parser')
        datos = {"Ticket": ticket_id}
        
        # Función auxiliar para buscar etiquetas <dt> y <dd>
        def buscar_campo(texto_etiqueta):
            dt = soup.find('dt', string=lambda x: x and texto_etiqueta in x)
            return dt.find_next_sibling('dd').text.strip() if dt else "N/A"

        datos.update({
            "Estado": buscar_campo("Estado:").upper(),
            "Técnico": buscar_campo("Asignado a:").title(),
            "Serie": buscar_campo("Serie:"),
            "Marca": buscar_campo("Marca:"),
            "Modelo": buscar_campo("Modelo:"),
            "Falla": buscar_campo("Falla:")
        })

        # Verificar si se pudieron leer los datos básicos
        if datos["Estado"] in ["N/A", ""] or datos["Serie"] in ["N/A", ""]:
            return "ERROR_NA"

        # Lógica para extraer el texto del Acta (Sustitución/Reemplazo)
        texto_acta = ""
        titulo_acta = "ACTA DE REEMPLAZO / SUSTITUCIÓN"
        modales = soup.find_all('div', id=['v_sustitucionModal', 'v_reemplazoModal'])
        
        for modal in modales:
            if "A PHP Error was encountered" in modal.text:
                continue 
            
            cuerpo = modal.find('div', class_='modal-body')
            if cuerpo:
                # Limpiar botones internos
                for btn in cuerpo.find_all(['button', 'a']):
                    btn.decompose()
                
                titulo_p = cuerpo.find('p', class_='pt-3')
                if titulo_p:
                    titulo_acta = titulo_p.get_text(strip=True).upper()
                
                h5_tags = cuerpo.find_all('h5')
                if h5_tags:
                    lineas = []
                    for h5 in h5_tags:
                        # Convertir <strong> a <b> para el PDF
                        html_h5 = "".join(str(item) for item in h5.contents)
                        html_h5 = html_h5.replace('<strong>', '<b>').replace('</strong>', '</b>')
                        lineas.append(html_h5)
                    texto_acta = "<br/><br/>".join(lineas)
                    break 

        # Extracción de accesorios del comprobante
        accesorios_recibidos = ""
        modal_comprobante = soup.find('div', id='v_comprobanteModal')
        if modal_comprobante:
            h5_tags = modal_comprobante.find_all('h5')
            for h5 in h5_tags:
                texto = h5.get_text()
                if "El equipo ha sido recibido con:" in texto:
                    accesorios_recibidos = texto
                    break

        datos["Accesorios_Recibidos"] = accesorios_recibidos
        datos["TextoActa"] = texto_acta
        datos["TituloActa"] = titulo_acta
        return datos
    except Exception as e: 
        print(f"Error de red: {e}")
        return None

# --- GENERADORES DE PDF (REPORTLAB) ---

def generar_pdf_vineta(datos, observacion, proveedor, detalle_extra=""):
    """Genera el PDF de la viñeta con columna estática, contenido elástico y mayúsculas."""
    path = os.path.join(tempfile.gettempdir(), f"Vineta_{datos['Ticket']}.pdf")
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=72, rightMargin=72, title=f"Proveedor-#{datos['Ticket']}")
    
    ticket_str = str(datos['Ticket']).upper()
    tecnico = str(datos['Técnico']).upper()
    marca_modelo = f"{datos['Marca']} / {datos['Modelo']}".upper()
    serie = str(datos['Serie']).upper()
    proveedor_str = str(proveedor).upper()
    observacion_str = str(observacion).upper()
    falla = str(datos['Falla']).upper()
    detalle_extra_str = str(detalle_extra).upper()
    
    ancho_pagina, alto_pagina = letter
    margen = 72
    ancho_max_disponible = ancho_pagina - (margen * 2)
    ancho_etiquetas = 125  
    ancho_max_contenido = ancho_max_disponible - ancho_etiquetas
    
    fuente = "Helvetica"
    tamano_fuente = 11
    
    textos_a_medir = [
        ticket_str, tecnico, marca_modelo, serie, 
        proveedor_str, observacion_str, "SANTA ANA", falla, detalle_extra_str
    ]
    
    ancho_necesario_max = 0
    for t in textos_a_medir:
        ancho_t = stringWidth(t, fuente, tamano_fuente)
        if ancho_t > ancho_necesario_max:
            ancho_necesario_max = ancho_t
            
    ancho_final_col2 = min(ancho_necesario_max + 20, ancho_max_contenido)
    
    elementos = []
    estilos = getSampleStyleSheet()
    estilo_celda = estilos["Normal"]
    estilo_celda.fontSize = tamano_fuente
    estilo_celda.fontName = fuente

    elementos.append(Paragraph("VIÑETA DE ENVÍO A PROVEEDOR", estilos["Title"]))
    elementos.append(Spacer(1, 20))

    data = [
        ["FECHA", ""], 
        ["TICKET", Paragraph(ticket_str, estilo_celda)], 
        ["TÉCNICO", Paragraph(tecnico, estilo_celda)], 
        ["MARCA / MODELO", Paragraph(marca_modelo, estilo_celda)],
        ["SERIE", Paragraph(serie, estilo_celda)], 
        ["PROVEEDOR", Paragraph(proveedor_str, estilo_celda)],
        ["OBSERVACIÓN", Paragraph(observacion_str, estilo_celda)], 
        ["SEDE", "SANTA ANA"], 
        ["FALLA", Paragraph(falla, estilo_celda)]
    ]
    
    if detalle_extra_str:
        data.append(["DETALLE", Paragraph(detalle_extra_str, estilo_celda)])
    
    tabla = Table(data, colWidths=[ancho_etiquetas, ancho_final_col2])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#e0e0e0")),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    
    elementos.append(tabla)
    doc.build(elementos)
    return path

def generar_pdf_acta(datos, ruta_dui):
    path = os.path.join(tempfile.gettempdir(), f"Acta_{datos['Ticket']}.pdf")
    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter
    estilo_acta = ParagraphStyle('ActaStyle', fontSize=12, leading=16, alignment=TA_CENTER)
    
    def dibujar_hoja(es_copia=False):
        c.setFont("Helvetica-Bold", 14)
        titulo = ( "COPIA DE RESPALDO - " if es_copia else "" ) + datos["TituloActa"]
        c.drawCentredString(w/2, 750, titulo)
        
        p = Paragraph(datos['TextoActa'], estilo_acta)
        t = Table([[p]], colWidths=[w - 100])
        t.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.black),
            ('PADDING', (0,0), (-1,-1), 15),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#fefefe"))
        ]))
        t.wrapOn(c, w - 100, 600)
        y_tabla = 720 - t._height
        t.drawOn(c, 50, y_tabla)
        
        if not es_copia and ruta_dui and os.path.exists(ruta_dui):
            img_w, img_h = 10 * cm, 6.3 * cm
            y_img = max(y_tabla - img_h - 40, 150)
            c.drawImage(ruta_dui, (w-img_w)/2, y_img, width=img_w, height=img_h)
            c.setFont("Helvetica", 10)
            c.drawCentredString(w/2, y_img - 60, "F._________________________________")
            c.drawCentredString(w/2, y_img - 75, "Recibido conforme (Firma)")

    dibujar_hoja(es_copia=False)
    c.showPage()
    dibujar_hoja(es_copia=True)
    c.save()
    return path

# --- RUTAS DE LA APLICACIÓN (ENDPOINTS) ---

@app.route('/')
def index():
    cookie_lista = os.path.exists(ARCHIVO_COOKIE)
    return render_template('index.html', creador=CREADOR, tiene_cookie=cookie_lista)

# --- SISTEMA DE LOGIN PARA ADMINISTRACIÓN ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Maneja el inicio de sesión del portal de administración."""
    # Si ya está logueado, lo mandamos directo al admin
    if session.get('admin_logueado'):
        return redirect('/admin')
        
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        
        # Validamos credenciales
        if usuario == 'admin' and password == 'admin':
            session['admin_logueado'] = True
            return redirect('/admin')
        else:
            flash("Credenciales incorrectas. Acceso denegado. ❌")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.pop('admin_logueado', None)
    return redirect('/login')

# --- PANEL DE ADMINISTRACIÓN DE EXCEL ---

@app.route('/admin')
def admin_portal():
    """Muestra la tabla de proveedores y los formularios de edición/carga."""
    if not session.get('admin_logueado'): return redirect('/login') # <-- Guardia de seguridad
    
    try:
        if not os.path.exists(RUTA_EXCEL):
            return "El archivo Excel no existe en el servidor. Súbelo primero.", 404
        
        df = pd.read_excel(RUTA_EXCEL, dtype=str)
        columnas = df.columns.tolist()
        datos = df.tail(100).reset_index().to_dict(orient='records') 
        return render_template('admin.html', columnas=columnas, datos=datos)
    except Exception as e:
        return f"Error al cargar portal admin: {e}", 500

@app.route('/api/agregar_fila', methods=['POST'])
def agregar_fila():
    if not session.get('admin_logueado'): return redirect('/login')
    try:
        nueva_data = request.form.to_dict()
        df = pd.read_excel(RUTA_EXCEL, dtype=str)
        df_nueva = pd.DataFrame([nueva_data])
        df = pd.concat([df, df_nueva], ignore_index=True)
        df.to_excel(RUTA_EXCEL, index=False)
        flash("¡Registro agregado correctamente al Excel! ✅")
        return redirect('/admin')
    except Exception as e:
        return f"Error al insertar fila: {e}", 500

@app.route('/api/editar_fila/<int:idx>', methods=['POST'])
def editar_fila(idx):
    if not session.get('admin_logueado'): return redirect('/login')
    try:
        nueva_data = request.form.to_dict()
        df = pd.read_excel(RUTA_EXCEL, dtype=str)
        for col in df.columns:
            if col in nueva_data:
                df.at[idx, col] = nueva_data[col]
        df.to_excel(RUTA_EXCEL, index=False)
        flash("¡Registro actualizado con éxito! ✏️")
        return redirect('/admin')
    except Exception as e:
        return f"Error al editar fila: {e}", 500

@app.route('/api/eliminar_fila/<int:idx>', methods=['POST'])
def eliminar_fila(idx):
    if not session.get('admin_logueado'): return redirect('/login')
    try:
        df = pd.read_excel(RUTA_EXCEL, dtype=str)
        if idx in df.index:
            df = df.drop(index=idx)
            df.to_excel(RUTA_EXCEL, index=False)
            flash("¡Registro eliminado permanentemente! 🗑️")
        return redirect('/admin')
    except Exception as e:
        return f"Error al eliminar fila: {e}", 500

@app.route('/actualizar_excel_completo', methods=['POST'])
def actualizar_excel_completo():
    if not session.get('admin_logueado'): return redirect('/login')
    archivo = request.files.get('excel_file')
    if archivo and archivo.filename.endswith(('.xlsx', '.xls')):
        archivo.save(RUTA_EXCEL)
        flash("¡Base de datos Excel reemplazada con éxito! 📁")
        return redirect('/admin')
    return "Archivo inválido.", 400

# --- RUTAS DE COOKIES Y PROCESAMIENTO ---

@app.route('/api/actualizar_cookie', methods=['POST', 'OPTIONS'])
def api_actualizar_cookie():
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, ngrok-skip-browser-warning'
        }
        return ('', 204, headers)

    try:
        datos = request.get_json(force=True)
        if datos and 'cookie' in datos:
            with open(ARCHIVO_COOKIE, "w") as f:
                f.write(datos['cookie'].strip())
            return jsonify({"status": "success"}), 200, {'Access-Control-Allow-Origin': '*'}
        return jsonify({"status": "error"}), 400, {'Access-Control-Allow-Origin': '*'}
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500, {'Access-Control-Allow-Origin': '*'}

@app.route('/update_cookie', methods=['POST'])
def update_cookie():
    datos = request.get_json(force=True)
    if datos and 'cookie' in datos:
        with open(ARCHIVO_COOKIE, "w") as f:
            f.write(datos['cookie'].strip())
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400

@app.route('/procesar_vineta', methods=['POST'])
def procesar_vineta():
    ticket = request.form.get('ticket')
    detalle = request.form.get('detalle', '')
    acc = []
    if request.form.get('caja'): acc.append("Caja")
    if request.form.get('cargador'): acc.append("Cargador")
    if request.form.get('funda'): acc.append("Funda")
    obs = ", ".join(acc) if acc else "SOLO EQUIPO"

    d = extraer_datos_web(ticket)
    if d == "ERROR_NA": return "Error: Ticket no encontrado o no existe.", 404
    if isinstance(d, str): return f"Error de sesión o conexión: {d}", 400
    if not d: return "Error: Ticket no encontrado o no existe.", 404
    
    estado = d.get("Estado", "").upper()
    if "PROCESO DE GARANT" not in estado:
        return f"Error: El ticket debe estar en 'Proceso de garantía'. Estado actual: {estado.title()}", 400
        
    prov = obtener_proveedor(d['Modelo'])
    pdf_path = generar_pdf_vineta(d, obs, prov, detalle)
    return send_file(pdf_path, as_attachment=False, download_name=f"Vineta_{ticket}.pdf")

@app.route('/procesar_acta', methods=['POST'])
def procesar_acta():
    ticket = request.form.get('ticket')
    img_file = request.files.get('dui_img')
    if not img_file: return "Error: Falta DUI.", 400
    
    d = extraer_datos_web(ticket)
    if d == "ERROR_NA": return "Error: Ticket no encontrado o no existe.", 404
    if isinstance(d, str): return f"Error de sesión o conexión: {d}", 400
    if not d: return "Error: Ticket no encontrado o no existe.", 404
    
    estado = d.get("Estado", "").upper()
    if "PROCESO DE GARANT" not in estado:
        return f"Error: El ticket debe estar en 'Proceso de garantía'. Estado actual: {estado.title()}", 400

    if not d.get("TextoActa"): return "Error: No hay acta disponible.", 404

    temp_img = os.path.join(tempfile.gettempdir(), secure_filename(img_file.filename))
    img_file.save(temp_img)
    pdf_path = generar_pdf_acta(d, temp_img)
    return send_file(pdf_path, as_attachment=False, download_name=f"Acta_{ticket}.pdf")

@app.route('/api/comprobar_ticket/<ticket_id>', methods=['GET'])
def comprobar_ticket(ticket_id):
    d = extraer_datos_web(ticket_id)
    if d == "ERROR_NA":
        return jsonify({"status": "error", "mensaje": "Ticket no encontrado o no existe."}), 404
    if isinstance(d, str):
        return jsonify({"status": "error", "mensaje": f"Error de sincronización o sesión: {d}"}), 400
    if not d:
        return jsonify({"status": "error", "mensaje": "Ticket no encontrado o no existe."}), 404
        
    estado = d.get("Estado", "").upper()
    if "PROCESO DE GARANT" not in estado:
        return jsonify({"status": "error", "mensaje": f"El ticket debe estar en 'Proceso de garantía'. Estado actual: {estado.title()}"}), 400
        
    acc = d.get("Accesorios_Recibidos", "").upper()
    
    return jsonify({
        "status": "success",
        "cargador": "CARGADOR" in acc,
        "caja": "CAJA" in acc,
        "funda": "FUNDA" in acc
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)