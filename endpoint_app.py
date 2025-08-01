from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
import requests
from google.cloud import bigquery
import json
import os
import datetime
from dotenv import load_dotenv
from utils import init_clients, process_tavily_json, parse_with_gemini, save_bigquery, obtener_datos_bigquery,obtener_base_url
from flask_cors import CORS


# Cargar variables de entorno
load_dotenv()
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
SERVICE_ACCOUNT_FILE = "/etc/secrets/atom-ai-labs.json"
#SERVICE_ACCOUNT_FILE = '/Users/pablorosa/Documents/crawler_app/my_agent/atom-ai-labs.json'
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

client_tavily, gemini_model = init_clients(TAVILY_API_KEY, GOOGLE_API_KEY)
app = Flask(__name__, template_folder='templates')

CORS(app)

@app.route('/hello_world', methods=['GET'])
def hello_world():
    return jsonify({'response': "Hola"})

@app.route('/chat_with_db', methods=['POST'])
def chat():
    print("📥 [chat_with_db] Recibí una request POST")
    
    data = request.get_json()
    print("🧾 Datos recibidos:", data)

    mensaje = data.get('message')
    system_prompt = data.get('system_prompt')
    project_id = data.get('project_id')
    dataset_id = data.get('dataset_id')
    table_id = data.get('table_id')
    historial = data.get('history_chat', [])  # puede venir vacío

    # Validación de campos obligatorios
    if not all([mensaje, system_prompt, project_id, dataset_id, table_id]):
        print("❌ Faltan campos obligatorios en la request")
        return jsonify({'error': 'Faltan campos obligatorios'}), 400

    try:
        print("🔑 Configurando Generative AI con la API key...")
        genai.configure(api_key=GOOGLE_API_KEY)

        def get_bigquery_data():
            """
            Obtiene y recupera datos ACTUALIZADOS del inventario de autos desde la base de datos de BigQuery.
            Utiliza esta herramienta OBLIGATORIAMENTE para CUALQUIER pregunta relacionada con:
            - Marcas, modelos o versiones de autos.
            - Precios, costos o valor de los vehículos.
            - Kilometraje (km), antigüedad o año de los autos.
            - Comparaciones entre dos o más autos.
            - Cantidad de autos en stock.
            - Especificaciones técnicas como motor, color, etc.
            Esta es la ÚNICA fuente de verdad para datos de inventario de autos.
            """
            print("📡 Llamando a función obtener_datos_bigquery()...")
            return obtener_datos_bigquery(project_id, dataset_id, table_id, SERVICE_ACCOUNT_FILE)

        print("🤖 Inicializando modelo Gemini...")
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            tools=[get_bigquery_data],
            system_instruction=system_prompt
        )

        print("🗨️ Iniciando sesión de chat con historial...")
        chat_session = model.start_chat(
            history=historial,
            enable_automatic_function_calling=True
        )

        print(f"📨 Enviando mensaje: {mensaje}")
        response = chat_session.send_message(mensaje)

        print("✅ Respuesta recibida del modelo:", response.text)

        return jsonify({
            'response': response.text,
            'timestamp': datetime.datetime.now().strftime('%H:%M:%S'),
        })

    except Exception as e:
        print("🔥 Error durante el procesamiento:", str(e))
        return jsonify({'error': f'Error procesando mensaje: {str(e)}'}), 500


@app.route('/chat')
def home():
    return render_template('index.html')

@app.route('/crawl-web', methods=['POST'])
def extraer_autos():
    data = request.get_json()
    url = data.get("url")
    project_id = data.get("project_id")
    dataset_id = data.get("dataset_id")
    industry_type = data.get("industry_type")
    fields = data.get("fields")
    
    
    if not url:
        print("❌ Error: Falta el parámetro 'url'")
        return jsonify({"error": "Falta el parámetro 'url'"}), 400

    try:
        print(f"🌐 [1] Iniciando crawl de: {url}")
        ## setear variable la url_base
        base_url = obtener_base_url(url)
        if industry_type == "automotive":
            tavili_instructions = (
                "Find and extract all the information about used cars."
                "including model, year, price, mileage, engine, fuel type, transmission, drive type, and unit number."
            )
        elif industry_type == "education":
            tavili_instructions = (
                "Find and extract all the information about university programs."
                "including program name, duration, modality, tuition fees, degree level, admission criteria, and the name of the university."
            )
        elif industry_type == "retail":
            tavili_instructions = (
                "Find and extract all the information about clothing and accessories ."
                "including item name, brand, category (e.g., shirts, pants), size options, colors, price, discount, and availability."
            )
        else:
            tavili_instructions = (
                "Find and extract all the relevant information about items or services."
                "including name, category or type, description, price (if available), availability, "
                "and any other useful attributes such as brand, specifications, or contact details.")


        tavily_response = client_tavily.crawl(url=url, instructions=tavili_instructions, limit=200, max_depth=5,select_paths=["/seminuevo"])
        print("✅ [2] Crawl completado. Procesando contenido...")

        textos_limpios = process_tavily_json(tavily_response)
        print(f"🧹 [3] Se limpiaron {len(textos_limpios)} bloques de texto.")

        df = parse_with_gemini(textos_limpios, gemini_model, fields, url)
        print(f"🤖 [4] Gemini extrajo {len(df)} autos.")

        print("📄 [5] Guardando en Big Query...")
        ok, _ = save_bigquery(df, project_id=project_id, dataset_id=dataset_id, cred_path=SERVICE_ACCOUNT_FILE)

        if not ok:
            print("❌ [6] Error al guardar en Big Query.")
            return jsonify({"error": "No se pudo guardar en Big Query"}), 500

        print("✅ [7] Proceso finalizado correctamente.")
        return jsonify(df)

    except Exception as e:
        print("❌ [!] Excepción detectada:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/shopify-to-bigquery", methods=["POST"])
def shopify_to_bigquery():
    data = request.get_json()
    domain = data.get("shopify_domain")
    access_token = data.get("access_token")
    api_version = data.get("api_version", "2024-04")
    project_id = data.get("project_id")
    dataset_id = data.get("dataset_id")
    cred_path = data.get("cred_path")

    if not all([domain, access_token, project_id, dataset_id, cred_path]):
        return jsonify({"error": "Faltan parámetros"}), 400

    try:
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }
        url = f"https://{domain}/admin/api/{api_version}/products.json?limit=250"
        resp = requests.get(url, headers=headers)

        if resp.status_code != 200:
            return jsonify({"error": "Error al consultar Shopify", "details": resp.text}), 500

        products_raw = resp.json().get("products", [])

        # Flatten productos (puede ajustarse según lo que quieras guardar)
        products = []
        for prod in products_raw:
            for variant in prod.get("variants", []):
                item = {
                    "product_id": prod.get("id"),
                    "product_title": prod.get("title"),
                    "variant_id": variant.get("id"),
                    "variant_title": variant.get("title"),
                    "sku": variant.get("sku"),
                    "price": variant.get("price"),
                    "inventory_quantity": variant.get("inventory_quantity"),
                    "product_vendor": prod.get("vendor"),
                    "product_type": prod.get("product_type"),
                    "created_at": prod.get("created_at"),
                    "status": prod.get("status"),
                    "tags": prod.get("tags"),
                    "main_image_url": prod.get("image", {}).get("src"),
                    "url_ref": f"https://{domain}/products/{prod.get('handle')}"
                }
                products.append(item)

        success, table_id = save_bigquery(products, project_id, dataset_id, cred_path)

        if not success:
            return jsonify({"error": "Error al subir a BigQuery"}), 500

        return jsonify({ "message": f"✅ Subidos {len(products)} productos a BigQuery",
                        "table_id": table_id
                        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/autoland-to-bigquery", methods=["POST"])
def autoland_to_bigquery():
    data = request.get_json()
    project_id = data.get("project_id")
    dataset_id = data.get("dataset_id")
    cred_path = data.get("cred_path")

    if not all([project_id, dataset_id, cred_path]):
        return jsonify({"error": "Faltan parámetros"}), 400

    try:
        url = "https://www.autoland.com.co/wp-json/vehiculosWhatsapp/v1/usados"
        body = {
            "precio_min": 0,
            "precio_max": 25000000000
        }

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=body)

        if response.status_code != 200:
            return jsonify({"error": "Error al consultar Autoland", "details": response.text}), 500

        data_autos = response.json()
        autos_raw = data_autos.get("autos", [])

        autos = []
        for auto in autos_raw:
            item = {
                "vehicle_id": auto.get("vehicle_id"),
                "title": auto.get("title"),
                "make": auto.get("make"),
                "year": auto.get("year"),
                "price": auto.get("price"),
                "sale_price": auto.get("sale_price"),
                "mileage": auto.get("mileage"),
                "transmission": auto.get("transmission"),
                "cilindraje": auto.get("cilindraje"),
                "url": auto.get("url"),
                "image_link": auto.get("image_link"),
                "serie": auto.get("serie"),
                "type": auto.get("type"),
                "city": auto.get("city"),
            }
            autos.append(item)

        table_id = "20250801_autoland"
        success, table_name = save_bigquery(autos, project_id, dataset_id, cred_path, table_id=table_id)

        if not success:
            return jsonify({"error": "Error al subir a BigQuery"}), 500

        return jsonify({
            "message": f"✅ Subidos {len(autos)} autos a BigQuery",
            "table_id": table_name
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5500))
    app.run(host="0.0.0.0", port=port, debug=True)
