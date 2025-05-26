from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from database import get_session, Search, WebPage, create_tables
from search import get_gemini_response, search_duckduckgo, perform_deep_search
import os
import markdown  # ensure this is imported
import json

app = Flask(__name__)

@app.template_filter('convert_markdown')
def convert_markdown(text):
    """Convert markdown text to HTML using desired extensions."""
    return markdown.markdown(
        text,
        extensions=['extra', 'fenced_code', 'codehilite', 'smarty', 'nl2br']
    )

# Функція для отримання API ключа з різних джерел
def get_api_key():
    # Спочатку перевіряємо змінну середовища
    key = os.environ.get('GOOGLE_API_KEY')
    
    # Якщо ключ не знайдено в змінних середовища, перевіряємо файл конфігурації
    if not key:
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'api_key.txt')
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    key = f.read().strip()
            except:
                pass
    
    return key

# Get API key from environment or config file
GOOGLE_API_KEY = get_api_key()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    search_type = request.form.get('search_type', 'shallow')
    session = get_session()

    if search_type == 'shallow':
        gemini_response = get_gemini_response(query, GOOGLE_API_KEY, detailed=True)
        search_results = search_duckduckgo(query)
        
        # Create a chat history with the first Q&A pair
        chat_history = [{
            "role": "user",
            "content": query
        }, {
            "role": "assistant",
            "content": gemini_response
        }]
        
        # Store the chat history as JSON in the database
        new_search = Search(
            query=query, 
            search_type=search_type, 
            response=gemini_response, 
            chat_history=json.dumps(chat_history)
        )
        session.add(new_search)
        session.commit()
        search_id = new_search.id
        session.close()
        
        # Return only the response section
        return render_template('response_section.html', 
                             search_type=search_type, 
                             gemini_response=gemini_response, 
                             search_results=search_results, 
                             user_query=query,
                             search_id=search_id,
                             chat_history=chat_history)
    elif search_type == 'deep':
        # Запускаємо глибокий пошук і отримуємо ID пошуку
        search_id = perform_deep_search(query, GOOGLE_API_KEY, session)
        
        # Отримуємо нову сесію, щоб запобігти проблемам з від'єднаними об'єктами
        session = get_session() 
        search_entry = session.query(Search).get(search_id)
        
        if not search_entry:
            session.close()
            print(f"КРИТИЧНА ПОМИЛКА: Запис пошуку з ID {search_id} не знайдено.")
            return render_template('index.html', error_message="Помилка: Дані глибокого пошуку не вдалося отримати.")

        # Отримуємо контент відповіді
        response_content = "Глибокий пошук не зміг згенерувати відповідь. Це може бути через проблеми зі збором даних з сайтів."
        try:
            session.refresh(search_entry)
            if search_entry.response is not None:
                response_content = search_entry.response
        except Exception as e:
            print(f"ПОМИЛКА: Не вдалося оновити чи отримати search_entry.response для ID {search_id}: {e}")
        
        # Отримуємо всі сторінки і зберігаємо лише необхідні атрибути в список словників
        # Цей підхід вирішує проблему відірваних об'єктів, оскільки ми працюємо з простими типами даних
        pages_data = []
        try:
            raw_pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
            for page in raw_pages:
                try:
                    # Витягуємо всі необхідні атрибути зараз, поки об'єкт прикріплений до сесії
                    pages_data.append({
                        'url': page.url,
                        'title': page.title or 'Сторінка без назви',
                        'icon_url': page.icon_url or '/static/default-favicon.png',
                        'content': page.content
                    })
                except Exception as page_error:
                    print(f"ПОМИЛКА при обробці сторінки: {page_error}")
        except Exception as pages_error:
            print(f"ПОМИЛКА при отриманні сторінок: {pages_error}")
        
        # Створюємо історію чату
        chat_history = [{
            "role": "user",
            "content": query
        }, {
            "role": "assistant",
            "content": response_content
        }]
        
        # Оновлюємо запис у БД
        search_entry.chat_history = json.dumps(chat_history)
        session.commit()
        session.close()
        
        # Повертаємо шаблон з даними
        return render_template('response_section.html', 
                            search_type=search_type, 
                            gemini_report=response_content, 
                            pages=pages_data,  # Тепер це список словників, а не об'єктів SQLAlchemy
                            search_id=search_id,
                            user_query=query,
                            chat_history=chat_history)
    return "Невідомий тип пошуку."

@app.route('/ask', methods=['POST'])
def ask_question():
    search_id = request.form['search_id']
    question = request.form['question']
    search_type = request.form.get('search_type', 'deep')  # Default to deep if not specified

    print(f"DEBUG: Received follow-up question: '{question}' for search_id: {search_id}, search_type: {search_type}")

    session = get_session()
    search_entry = session.query(Search).get(search_id)
    
    if not search_entry:
        session.close()
        return "Помилка: Пошук не знайдено."
    
    # Load the existing chat history
    chat_history = json.loads(search_entry.chat_history) if search_entry.chat_history else []
    
    # Extract all questions and answers in a clear format for context
    conversation_context = ""
    for i in range(0, len(chat_history), 2):
        if i+1 < len(chat_history):
            user_q = chat_history[i]['content']
            ai_a = chat_history[i+1]['content']
            conversation_context += f"Запитання: {user_q}\nВідповідь: {ai_a}\n\n"
    
    if GOOGLE_API_KEY:
        if search_type == 'deep':
            # Отримуємо веб-сторінки та витягуємо їх дані одразу
            pages_data = []
            
            try:
                raw_pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
                for page in raw_pages:
                    try:
                        # Витягуємо всі необхідні атрибути зараз, поки об'єкт прикріплений до сесії
                        pages_data.append({
                            'url': page.url,
                            'title': page.title or 'Сторінка без назви',
                            'icon_url': page.icon_url or '/static/default-favicon.png',
                            'content': page.content or ''
                        })
                    except Exception as page_error:
                        print(f"ПОМИЛКА при обробці сторінки в блоці else: {page_error}")
            except Exception as pages_error:
                print(f"ПОМИЛКА при отриманні сторінок в блоці else: {pages_error}")
            
            # Generate a detailed response for deep search follow-up question
            print(f"DEBUG: Processing deep search follow-up question: {question}")
            prompt = f"""Це додаткове питання до нашої розмови про {search_entry.query}: "{question}"

            Попередня розмова:
            {conversation_context}
            
            Інструкції:
            1. Відповідай мовою запитання
            2. Надай детальну, ґрунтовну та інформативну відповідь
            3. Використовуй інформацію з тих джерел, які були проаналізовані раніше
            4. Якщо це запит про значення чогось - поясни глибоко, дай розгорнутий огляд
            5. Структуруй відповідь з використанням заголовків, списків та інших елементів форматування
            6. Надавай приклади, порівняння та детальні пояснення
            7. Не використовуй фрази типу "Згідно з джерелами" або "Як я вже згадував"
            """
            
            gemini_answer = get_gemini_response(prompt, GOOGLE_API_KEY, detailed=True)
            
            # Update chat history with the new Q&A pair
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": gemini_answer})
            search_entry.chat_history = json.dumps(chat_history)
            session.commit()
            
            # Prepare template variables
            template_vars = {
                'search_type': 'deep',
                'gemini_report': search_entry.response,
                'pages': pages_data,  # Тепер використовується список словників
                'gemini_answer': gemini_answer,
                'user_question': question,
                'search_id': search_id,
                'user_query': search_entry.query,
                'chat_history': chat_history            }
            
        else:  # shallow search
            # Improved shallow follow-up question prompt with better context
            prompt = f"""Це додаткове питання до нашої розмови: "{question}"

            Попередня розмова:
            {conversation_context}
            
            Інструкції:
            1. Відповідай мовою запитання
            2. Надай детальну та інформативну відповідь
            3. Якщо це запит про значення чогось - поясни, що це таке і дай ґрунтовний огляд
            4. Якщо це конкретне питання - надай повну відповідь з усіма важливими деталями
            5. Не використовуй фрази типу "Як я згадував раніше" або "Як було сказано"
            6. Структуруй відповідь для кращого розуміння, використовуй форматування
            7. Надавай приклади та пояснення, де це доречно
            """
            
            print(f"DEBUG: Sending prompt to Gemini (shallow): {prompt[:200]}...")
            gemini_answer = get_gemini_response(prompt, GOOGLE_API_KEY, detailed=True)
            print(f"DEBUG: Received Gemini response (shallow): {gemini_answer[:200]}...")
            search_results = search_duckduckgo(question)
            
            # Update chat history with the new Q&A pair
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": gemini_answer})
            search_entry.chat_history = json.dumps(chat_history)
            session.commit()
            
            # Prepare template variables
            template_vars = {
                'search_type': 'shallow',
                'gemini_response': search_entry.response,
                'search_results': search_results,
                'gemini_answer': gemini_answer,
                'user_question': question,
                'search_id': search_id,
                'user_query': search_entry.query,
                'chat_history': chat_history
            }
    else:
        gemini_answer = "Помилка: Не налаштовано API key для Gemini."
        template_vars = {
            'search_type': search_type,
            'gemini_answer': gemini_answer,
            'user_question': question,
            'search_id': search_id,
            'user_query': search_entry.query,
            'chat_history': chat_history
        }
        
        if search_type == 'deep':
            pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
            
            # Refresh each page object to ensure they are attached to the session
            for page in pages:
                try:
                    session.refresh(page)
                except Exception as e:
                    print(f"ERROR: Could not refresh page object with ID {page.id if hasattr(page, 'id') else 'Unknown'} in else block: {e}")
                    
            template_vars.update({
                'gemini_report': search_entry.response,
                'pages': pages
            })
        else:
            search_results = search_duckduckgo(question)
            template_vars.update({
                'gemini_response': search_entry.response,
                'search_results': search_results
            })
    
    session.close()
    
    print(f"DEBUG: Returning template with variables: {list(template_vars.keys())}")
    
    # Pass all variables to the template - return index.html as expected by frontend
    return render_template('index.html', **template_vars)

@app.route('/settings')
def settings():
    return render_template('settings.html', api_key=GOOGLE_API_KEY)

@app.route('/save-settings', methods=['POST'])
def save_settings():
    global GOOGLE_API_KEY
    api_key = request.form.get('api_key', '').strip()
    
    if api_key:
        # Оновлюємо змінну API ключа в поточній сесії
        GOOGLE_API_KEY = api_key
        
        # Зберігаємо API ключ в файл конфігурації для майбутніх запусків
        try:
            config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            
            with open(os.path.join(config_dir, 'api_key.txt'), 'w') as f:
                f.write(api_key)
                
            return render_template('settings.html', api_key=api_key, success_message="API ключ успішно збережено!")
        except Exception as e:
            return render_template('settings.html', api_key=api_key, error_message=f"Помилка збереження ключа: {str(e)}")
    else:
        # Якщо ключ порожній, очищаємо його
        GOOGLE_API_KEY = None
        
        # Видаляємо файл конфігурації, якщо він існує
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'api_key.txt')
        if os.path.exists(config_file):
            os.remove(config_file)
            
        return render_template('settings.html', api_key='', info_message="API ключ очищено.")

@app.route('/static/<filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    import os
    if not os.path.exists('deepscout.db'):
        create_tables()  # Create tables if DB doesn't exist
    app.run(debug=True)