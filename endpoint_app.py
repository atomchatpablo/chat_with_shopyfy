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
#SERVICE_ACCOUNT_FILE = "/etc/secrets/atom-ai-labs.json"
SERVICE_ACCOUNT_FILE = '/Users/pablorosa/Documents/crawler_app/my_agent/atom-ai-labs.json'
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

client_tavily, gemini_model = init_clients(TAVILY_API_KEY, GOOGLE_API_KEY)
app = Flask(__name__, template_folder='templates')
CORS(app, resources={r"/proxy_chat": {"origins": ["http://127.0.0.1:5500", 
                                                    "http://localhost:5500"]}}) # Ajusta los orígenes permitidos

# Define la URL del endpoint externo (donde antes hacías fetch desde el frontend)
EXTERNAL_API_URL = "https://flask-function-a6b6bgt5hq-uc.a.run.app/chat_with_db"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/proxy_chat', methods=['POST'])
def proxy_chat():
    """
    Esta ruta proxy recibe el mensaje del frontend,
    lo reenvía al endpoint externo, y retorna la respuesta al frontend.
    """
    try:
        # Recibe el mensaje y otros datos necesarios del frontend
        data = request.get_json()
        message = data['message']
        company_id = data['company_id']
        history_chat = data['history_chat'] 
        system_prompt = data['system_prompt'] 
        payload = {
            "message": message,
            "project_id": "atom-ai-labs-ad1fa",
            "dataset_id": "chat_with_web",
            "company_id": company_id,
            "history_chat": history_chat,
            "system_prompt": system_prompt
        }

        response = requests.post(
            EXTERNAL_API_URL,
            headers={'Content-Type': 'application/json'},
            data=json.dumps(payload)
        )    
        response.raise_for_status() 
        external_data = response.json()
        return jsonify(external_data)

    except requests.exceptions.RequestException as e:
        print(f"Error al comunicarse con el endpoint externo: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        # Maneja otros errores
        print(f"Error inesperado: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5500))
    app.run(host="0.0.0.0", port=port, debug=True)