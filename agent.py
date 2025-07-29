import google.generativeai as genai
import gspread
import json
import os
import datetime

# export GOOGLE_API_KEY="api_key"


GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
SERVICE_ACCOUNT_FILE = '/Users/pablorosa/Documents/crawler_app/my_agent/atom-ai-labs.json'
SPREADSHEET_NAME = 'purdy'
SYSTEM_PROMPT = """
Eres un asesor de ventas del Grupo Purdy. Tu tarea es ayudar a los usuarios a responder sus consultas sobre los diferentes autos que tenemos actualmente disponibles.

Reglas y contexto que SIEMPRE debes seguir:

1. **Tono y Personalidad:** Sé siempre amable, profesional y conciso.
2. **Contexto:** La empresa es Grupo Purdy, vende los mejores autos usados de Panamá.
3. **Límites:** No inventes información. Si no tienes un dato, indícalo.
4. **Idioma:** Siempre responde en español.
5. **Longitud de respuesta:** Tus respuestas no deben tener más de 100 palabras.
6. **Formato de respuesta:** Estructura la respuesta en forma de bullets cuando sea útil.
7. **Emojis:** Usa emojis solo si aportan claridad o cercanía.
8. **Cantidad de resultados:**
   - Muestra como máximo 3 autos por respuesta.
   - Si hay más de 10 resultados, **no muestres autos todavía**.
   - En ese caso, ayudá al usuario a filtrar haciendo preguntas como:
     - ¿Qué tipo de vehículo estás buscando? (sedán, SUV, camioneta...)
     - ¿Tenés alguna marca o modelo en mente?
     - ¿Año aproximado?
     - ¿Rango de kilómetros?
   - **Pero si después de 1 o 2 preguntas** lográs reducir los resultados a **10 o menos**, ahí sí podés mostrar las opciones (máximo 3 en la respuesta, ofreciendo seguir viendo si quiere).
9. **Proactividad:** Si el usuario no da todos los datos, orientalo con preguntas útiles para reducir los resultados sin abrumarlo.

Ejemplo de conversación:

- Usuario: "Quiero una Toyota"
- Asistente: "¡Genial! Tenemos varias opciones de la marca Toyota 🚗 ¿Qué tipo de vehículo estás buscando? (sedán, SUV, camioneta...)"
- Usuario: "Una camioneta"
- Asistente: "Muy buena elección, tenes camionetas de diferentes marcas, pero para ayudarte, me podrias decir que marca estas buscando?"
- Usuario: "Toyota"
- Asistente: "Toyota es una marca que se caracteriza por su seguridad y potencia. Buscas algun color en particular? kilometraje? de que año te interesa que sea?"
- Usuario: "que tenga mayor al 2019"
- Asistente: "Perfecto. Estas son las opciones disponibles:"
   - Toyota Hilux 2021 - 40,000 km
   - Toyota Fortuner 2020 - 60,000 km
   - Toyota Tacoma 2019 - 75,000 km
   Hay más disponibles si querés ver otras opciones 😉
"""

def current_time_str():
    return datetime.datetime.now().strftime('%H:%M:%S')

# --- HERRAMIENTA DE ACCESO A GOOGLE SHEET ---
def obtener_datos_de_la_hoja():
    """
    Se conecta a la Google Sheet llamada 'purdy' y extrae todos los datos.
    Devuelve los datos como una lista de diccionarios en formato JSON,
    donde cada diccionario es una fila de la hoja.
    """
    try:
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        spreadsheet = gc.open(SPREADSHEET_NAME)
        worksheet = spreadsheet.sheet1
        records = worksheet.get_all_records()
        print(f"DEBUG: Se han extraído {len(records)} filas de la hoja.")
        return json.dumps(records)
    except gspread.exceptions.SpreadsheetNotFound:
        error_msg = f"Error: No se encontró una Google Sheet con el nombre '{SPREADSHEET_NAME}'. Revisa el nombre y los permisos de compartir."
        print(error_msg)
        return json.dumps({"error": error_msg})
    except Exception as e:
        error_msg = f"Error inesperado al acceder a la Google Sheet: {e}"
        print(error_msg)
        return json.dumps({"error": error_msg})

def iniciar_chat_con_agente():
    """
    Configura e inicia el ciclo de conversación con el agente de IA.
    """
    if not GOOGLE_API_KEY:
        print("Error: La variable de entorno GOOGLE_API_KEY no está configurada.")
        return

    # Configura el cliente de la API de Gemini
    genai.configure(api_key=GOOGLE_API_KEY)

    model = genai.GenerativeModel(
        model_name='gemini-2.5-flash',
        tools=[obtener_datos_de_la_hoja],
        system_instruction=SYSTEM_PROMPT

    )

    # Inicia una sesión de chat interactiva
    chat = model.start_chat(enable_automatic_function_calling=True)

    print("🤖 ¡Hola! Soy tu agente experto en la hoja de cálculo 'Reporte de Personal'.")
    print("   Puedes hacerme preguntas como: '¿Cuál es el salario promedio?' o '¿Quién es el empleado más nuevo?'")
    print("   Escribe 'salir' para terminar la conversación.")

    while True:
        # Muestro el prompt con tiempo actual (antes de input)
        print(f"{current_time_str()} 👤 Tú: ", end='', flush=True)
        user_input = input()
        marca = current_time_str()  # capturo la hora justo después de pulsar Enter

        # Muestro confirmación con hora precisa
        print(f"--> Enviaste el mensaje a las ({marca}) y dijiste: {user_input}")

        if user_input.lower() == 'salir':
            print(f"{current_time_str()} 🤖 Ha sido un placer. ¡Hasta la próxima!")
            break

        # Envío al agente
        response = chat.send_message(user_input)
        # Muestro respuesta con timestamp
        print(f"{current_time_str()} 🤖 Agente: {response.text}")

if __name__ == '__main__':
    iniciar_chat_con_agente()