from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from database import get_session, Search, WebPage, create_tables
from search import get_gemini_response, search_duckduckgo, perform_deep_search
import os
import markdown  # ensure this is imported

app = Flask(__name__)

@app.template_filter('convert_markdown')
def convert_markdown(text):
    """Convert markdown text to HTML using desired extensions."""
    return markdown.markdown(
        text,
        extensions=['extra', 'fenced_code', 'codehilite', 'smarty', 'nl2br']
    )

# Отримуємо API key з оточення
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
        new_search = Search(query=query, search_type=search_type, response=gemini_response)
        session.add(new_search)
        session.commit()
        session.close()
        # Return only the response section
        return render_template('response_section.html', 
                             search_type=search_type, 
                             gemini_response=gemini_response, 
                             search_results=search_results, 
                             user_query=query)
    elif search_type == 'deep':
        search_id = perform_deep_search(query, GOOGLE_API_KEY, session)
        session = get_session()
        search_entry = session.query(Search).get(search_id)
        pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
        session.close()
        gemini_report_html = markdown.markdown(
            search_entry.response,
            extensions=['extra', 'fenced_code', 'codehilite', 'smarty', 'nl2br']
        )
        # Return only the response section
        return render_template('response_section.html', 
                             search_type=search_type, 
                             gemini_report=gemini_report_html, 
                             pages=pages, 
                             user_query=query)
    return "Невідомий тип пошуку."

@app.route('/ask', methods=['POST'])
def ask_question():
    search_id = request.form['search_id']
    question = request.form['question']

    session = get_session()
    search_entry = session.query(Search).get(search_id)
    if not search_entry:
        session.close()
        return "Помилка: Пошук не знайдено."

    pages = session.query(WebPage).filter(WebPage.search_id == search_id).all()
    context = ""
    for page in pages:
        context += f"\n\n# {page.title}\n\n{page.content}"
    if GOOGLE_API_KEY:
        prompt = f"Дай відповідь на запитання: {question}, базуючись на цій інформації: {context}"
        gemini_answer = get_gemini_response(prompt, GOOGLE_API_KEY)
        gemini_answer_html = markdown.markdown(
            gemini_answer,
            extensions=['extra', 'fenced_code', 'codehilite', 'smarty', 'nl2br']
        )
    else:
        gemini_answer_html = "Помилка: Не налаштовано API key для Gemini."
    session.close()
    # Pass the additional question as user_question
    return render_template('index.html', search_type='deep', 
                           gemini_report=markdown.markdown(search_entry.response, 
                               extensions=['extra', 'fenced_code', 'codehilite', 'smarty', 'nl2br']),
                           pages=pages, gemini_answer=gemini_answer_html, user_question=question)

@app.route('/static/<filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    import os
    if not os.path.exists('deepscout.db'):
        create_tables()  # Створюємо таблиці, якщо БД не існує
    app.run(debug=True)