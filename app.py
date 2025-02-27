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

# Get API key from environment
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    search_type = request.form.get('search_type', 'shallow')
    session = get_session()

    if search_type == 'shallow':
        gemini_response = get_gemini_response(query, GOOGLE_API_KEY)
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
        search_id = perform_deep_search(query, GOOGLE_API_KEY, session)
        session = get_session()
        search_entry = session.query(Search).get(search_id)
        pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
        
        # Create a chat history with the first Q&A pair
        chat_history = [{
            "role": "user",
            "content": query
        }, {
            "role": "assistant",
            "content": search_entry.response
        }]
        
        # Update the search entry with the chat history
        search_entry.chat_history = json.dumps(chat_history)
        session.commit()
        session.close()
        
        # Return only the response section
        return render_template('response_section.html', 
                             search_type=search_type, 
                             gemini_report=search_entry.response, 
                             pages=pages,
                             search_id=search_id,
                             user_query=query,
                             chat_history=chat_history)
    return "Невідомий тип пошуку."

@app.route('/ask', methods=['POST'])
def ask_question():
    search_id = request.form['search_id']
    question = request.form['question']
    search_type = request.form.get('search_type', 'deep')  # Default to deep if not specified

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
            # For deep search, use the web pages as context
            pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
            page_context = ""
            for page in pages:
                page_context += f"\n\n# {page.title}\n\n{page.content}"
            
            # Improved deep follow-up question prompt with better context handling
            prompt = f"""Це додаткове питання до нашої розмови: "{question}"

            Попередня розмова:
            {conversation_context}
            
            Інструкції:
            1. Відповідай мовою питання
            2. Надай інформативну, але лаконічну відповідь
            3. Спирайся на інформацію з джерел і попередньої розмови
            4. Не використовуй фрази типу "Згідно з джерелами" або "На основі наданої інформації"
            5. Уникай вступних фраз та зайвих пояснень 
            6. Форматуй текст з мінімальним використанням заголовків
            7. Посилайся на джерела лише якщо це критично важливо
            
            Інформація з джерел:
            {page_context}
            """
            
            gemini_answer = get_gemini_response(prompt, GOOGLE_API_KEY)
            
            # Update chat history with the new Q&A pair
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": gemini_answer})
            search_entry.chat_history = json.dumps(chat_history)
            session.commit()
            
            # Prepare template variables
            template_vars = {
                'search_type': 'deep',
                'gemini_report': search_entry.response,
                'pages': pages,
                'gemini_answer': gemini_answer,
                'user_question': question,
                'search_id': search_id,
                'user_query': search_entry.query,
                'chat_history': chat_history
            }
            
        else:  # shallow search
            # Improved shallow follow-up question prompt with better context
            prompt = f"""Це додаткове питання до нашої розмови: "{question}"

            Попередня розмова:
            {conversation_context}
            
            Інструкції:
            1. Відповідай мовою запитання
            2. Надай інформативну, але лаконічну відповідь
            3. Якщо це запит про значення чогось - поясни, що це таке і дай короткий огляд
            4. Якщо це конкретне питання - надай пряму відповідь з підтверджуючими деталями
            5. Не використовуй фрази типу "Як я згадував раніше" або "Як було сказано"
            6. Уникай вступних і підсумкових речень
            7. Використовуй структурований формат тексту, але мінімізуй кількість заголовків
            """
            
            gemini_answer = get_gemini_response(prompt, GOOGLE_API_KEY)
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
    
    # Pass all variables to the template
    return render_template('index.html', **template_vars)

@app.route('/settings')
def settings():
    return render_template('settings.html', api_key=GOOGLE_API_KEY)

@app.route('/save-settings', methods=['POST'])
def save_settings():
    api_key = request.form.get('api_key', '')
    # In a real app, you'd want to save this to a secure storage
    # Here we're just directing users back to the homepage
    return redirect(url_for('index'))

@app.route('/static/<filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    import os
    if not os.path.exists('deepscout.db'):
        create_tables()  # Create tables if DB doesn't exist
    app.run(debug=True)