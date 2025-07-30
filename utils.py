import re
import json
from urllib.parse import urlparse
from tavily import TavilyClient
from google.generativeai import GenerativeModel, GenerationConfig
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.cloud import bigquery
from urllib.parse import urlparse
import datetime
import tiktoken


def count_tokens(text, model="gpt-3.5-turbo"):
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))


# --- Tavily y Gemini setup ---
def init_clients(tavily_api_key, google_api_key):
    tavily = TavilyClient(tavily_api_key)

    gemini = GenerativeModel(
        model_name="gemini-1.5-flash-latest",
        generation_config=GenerationConfig(
            temperature=0.2,
            top_p=1,
            top_k=32,
            max_output_tokens=2048
        ),
        safety_settings={
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        },
    )

    return tavily, gemini


# --- Limpieza de HTML ---
def clean_html(raw_html):
    clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
    clean_text = re.sub(r'https?://\S+', ' ', clean_text)
    clean_text = re.sub(r'!\[.*?\]\(.*?\)', ' ', clean_text)
    clean_text = re.sub(r'\[.*?\]\(.*?\)', ' ', clean_text)
    clean_text = re.sub(r'[\n\r\t\xa0]', ' ', clean_text)
    clean_text = re.sub(r' +', ' ', clean_text)
    return clean_text.strip()

def process_tavily_json(tavily_json):
    all_clean_texts = []
    for item in tavily_json.get("results", []):
        raw = item.get("raw_content")
        if isinstance(raw, str):
            text = clean_html(raw)
            all_clean_texts.append(text)
        else:
            print("⚠️ raw_content no es string: ", type(raw), raw)
    return all_clean_texts


def parse_with_gemini(all_clean_texts, gemini_model, fields, url):
    field_example = ",\n".join([f'    "{field}": str' if field != "precio" else f'    "{field}": float' for field in fields])
    json_example = f"{{\n{field_example}\n}}"
    # setear que todo el codigo no tenga cosas hardcodeadas hacia purdy
    system_instructions = f"""Quiero que extraigas información sobre **todos los productos** que encuentres en el texto, en formato JSON, y devuelvas una lista con uno o más objetos como este:

    {json_example}

    Instrucciones importantes:

    1. Solo incluí en la lista los productos que tengan **todos** los campos completos.
    2. Si en el texto solo aparece una marca sin modelo o precio, **no lo incluyas**.
    3. La clave `url_ref` debe armarse concatenando la base `{url}`. Aqui debes cargar la url del producto especifico. De modo tal que pueda ver el producto que me das, pero en la web.
    4. Devolvé **únicamente la lista de JSONs**. Nada más. No uses texto adicional.
    5. En la descripcion debes incluir todas las caracteristicas relacionados a la descripción del producto.

    """

    result = []
    token_report = []

    for texto in all_clean_texts:
        try:
            if not isinstance(texto, str):
                print("⚠️ Se descartó un bloque no string:", type(texto))
                continue

            prompt = system_instructions + "\n\n" + texto
            input_token_count = count_tokens(prompt)

            response = gemini_model.generate_content(
                contents=[{"role": "user", "parts": [prompt]}]
            )
            respuesta = response.text.strip()
            output_token_count = count_tokens(respuesta)

            token_report.append({
                "Q_input_token": input_token_count,
                "Q_output_token": output_token_count
            })

            # el resto del código de parseo
            if respuesta.startswith("```"):
                respuesta = respuesta.replace("```json", "").replace("```", "").strip()

            respuesta_limpia = re.sub(r'\\[^\\"/bfnrtu]', '', respuesta)
            rows = json.loads(respuesta_limpia)

            if isinstance(rows, dict):
                rows = [rows]

            result.append(rows)

        except Exception as e:
            print("⚠️ Error procesando entrada:", e)
            continue

    # Al final podés guardar el resultado en un archivo si querés
    with open("tokens_por_consulta.json", "w") as f:
        json.dump(token_report, f, indent=2)

    flat_result = [item for sublist in result for item in sublist]
    return flat_result

def infer_schema_from_json(sample_obj):
    schema = []
    for key, value in sample_obj.items():
        if isinstance(value, str):
            field_type = "STRING"
        elif isinstance(value, int):
            field_type = "INT64"
        elif isinstance(value, float):
            field_type = "FLOAT64"
        elif isinstance(value, bool):
            field_type = "BOOL"
        else:
            field_type = "STRING"  # default fallback

        schema.append(bigquery.SchemaField(name=key, field_type=field_type))
    return schema



def obtener_base_url(url):
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")  # elimina 'www.' si está
    path = parsed.path.strip("/")               # elimina '/' inicial y final
    base_url = f"{netloc}/{path}" if path else netloc
    return base_url



def save_bigquery(raw_data, project_id, dataset_id, cred_path, table_id=None):
    try:
        if not raw_data:
            print("⚠️ No hay datos para guardar.")
            return False, None

        client = bigquery.Client.from_service_account_json(cred_path)

        # 👉 Armar nombre de tabla dinámica si no se pasa una explícita
        if table_id is None:
            today = datetime.datetime.now().strftime('%Y%m%d')
            sample_url = raw_data[0].get("url_ref") or raw_data[0].get("url", "https://default.com")
            domain = urlparse(sample_url).netloc.replace("www.", "").split(".")[0]
            table_name = f"{today}_{domain}"
        else:
            table_name = table_id

        full_table_id = f"{project_id}.{dataset_id}.{table_name}"

        # Verificar si la tabla ya existe
        table_exists = True
        try:
            client.get_table(full_table_id)
        except:
            table_exists = False

        # Crear tabla si no existe
        if not table_exists:
            schema = infer_schema_from_json(raw_data[0])
            table = bigquery.Table(full_table_id, schema=schema)
            client.create_table(table)
            print(f"📄 Tabla creada: {full_table_id}")

        # Insertar los datos
        errors = client.insert_rows_json(
            table=full_table_id,
            json_rows=raw_data,
            row_ids=[None] * len(raw_data),
        )

        if errors:
            print("❌ Errores al insertar:", errors)
            return False, None

        print(f"✅ Se insertaron {len(raw_data)} registros en {full_table_id}")
        return True, full_table_id

    except Exception as e:
        print("❌ Error general en save_bigquery:", e)
        return False, None



def obtener_datos_bigquery(project_id, dataset_id, table_id, cred_path):
    try:
        client = bigquery.Client.from_service_account_json(cred_path)
        query = f"SELECT * FROM `{project_id}.{dataset_id}.{table_id}`"
        query_job = client.query(query)
        results = query_job.result()
        records = [dict(row.items()) for row in results]
        return json.dumps(records)
    except Exception as e:
        print("no pasa query")
        return json.dumps({"error": str(e)})()
