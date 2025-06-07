import logging
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
import time
from utils import get_favicon, parse_page_content
from database import Search, WebPage

logging.basicConfig(level=logging.INFO)

def get_gemini_response(query, api_key, detailed=False, context="", is_followup=False):
    if not api_key:
        return "Помилка: Не налаштовано API key для Gemini."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        # Concise system prompt for short, direct responses
        system_prompt = """Ти - DeepScout AI, компактний дослідницький асистент.

СТИЛЬ ВІДПОВІДЕЙ:
- Коротко і по суті
- Лаконічно та зрозуміло
- Тільки найважливіша інформація
- Мінімум слів, максимум сенсу

ПРИНЦИПИ:
1. Відповідай тією ж мовою, що й запитання
2. Надавай точну та актуальну інформацію
3. Структуруй коротко (заголовки, списки)
4. Фокусуйся на практичності

ФОРМАТ:
- Основна відповідь: 2-4 речення
- Список ключових пунктів (якщо потрібно)
- Конкретні факти без води

ЗАБОРОНЕНО:
- Довгі пояснення та розтягнуті тексти
- Фрази "згідно з джерелами"
- Надмірні деталі та контекст
- Повторення та перефразування"""

        if is_followup and context:
            followup_prompt = f"""{system_prompt}

РЕЖИМ FOLLOW-UP:
Обробляєш додаткове питання в контексті розмови.

КОНТЕКСТ: {context}

АЛГОРИТМ:
1. Перевір зв'язок з попередньою темою
2. Якщо пов'язано - дай коротку відповідь у контексті
3. Якщо не пов'язано - повідом про зміну теми та запропонуй нову розмову

НОВЕ ПИТАННЯ: "{query}"

Відповідь має бути короткою (1-3 речення)."""
            query = followup_prompt
        
        elif detailed:
            enhanced_query = f"""{system_prompt}

РЕЖИМ ДЕТАЛЬНОГО АНАЛІЗУ:
Надай структуровану відповідь з ключовими аспектами теми.

ЗАПИТ: "{query}"

СТРУКТУРА:
1. Основна суть (2-3 речення)
2. Ключові пункти (3-5 коротких пунктів)
3. Практичні моменти (якщо є)

Загальний обсяг: до 10 речень."""
            query = enhanced_query
        else:
            query = f"{system_prompt}\n\nЗАПИТ: {query}\n\nНадай точну та корисну відповідь."
        
        # Generate response
        response = model.generate_content(query)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Error in get_gemini_response: {e}")
        return f"Помилка при отриманні відповіді від Gemini: {str(e)}"

def generate_sub_queries(query, api_key, num_queries=5):
    """
    Generates related search queries using Gemini.
    Improved prompt to generate more precise sub-queries for web scraping.
    """
    if not api_key:
        return ["Помилка: Не налаштовано API key для Gemini."]

    system_prompt = """Ти - експерт з пошуку інформації в Інтернеті. Твоє завдання - створювати ефективні пошукові запити.

ПРАВИЛА СТВОРЕННЯ ЗАПИТІВ:
1. Визнач мову оригінального запиту і використовуй ту саму мову
2. Створюй конкретні та цільові запити
3. Уникай занадто загальних або занадто вузьких запитів
4. Формулюй запити так, щоб знайти різні аспекти теми
5. Включай синоніми та альтернативні формулювання
6. Додавай запити для історичного контексту та сучасного стану

ФОРМАТ ВІДПОВІДІ:
- Повертай ТІЛЬКИ список запитів
- По одному запиту на рядок
- БЕЗ нумерації, тире або інших символів
- БЕЗ пояснень або коментарів"""

    prompt = f"""{system_prompt}

ОРИГІНАЛЬНИЙ ЗАПИТ: "{query}"

Створи {num_queries} різноманітних пошукових запитів, які допоможуть зібрати максимально повну інформацію про цю тему з різних джерел і perspectives."""

    sub_queries = get_gemini_response(prompt, api_key, detailed=False).splitlines()
    
    # Filter out any lines that might be empty or contain unwanted characters
    filtered_queries = [q.strip() for q in sub_queries if q.strip() and not q.strip().startswith(('•', '-', '*', '1.', '2.', '3.', '4.', '5.'))]
    return filtered_queries[:num_queries]

def search_duckduckgo(query, num_results=10):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    search_url = f"https://duckduckgo.com/?q={query}"
    driver.get(search_url)

    results = []
    try:
        for _ in range(2):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        link_elements = driver.find_elements(By.CSS_SELECTOR, "article[data-nrn='result'] a[data-testid='result-title-a']")
        for link in link_elements[:num_results]:
            title = link.text.strip()
            url = link.get_attribute('href')
            if title and url:
                results.append({'title': title, 'url': url})
    except Exception as e:
        logging.error(f"Помилка при отриманні результатів: {e}")

    driver.quit()
    return results

def perform_deep_search(query, api_key, session):
    """
    Виконує глибокий пошук: генерує підзапити, збирає URL, витягує вміст сторінок і зберігає в БД.
    Покращена логіка для кращого отримання контенту та обробки помилок.
    """
    # 1. Генеруємо підзапити (обмежуємо до 3 для швидкості)
    sub_queries = generate_sub_queries(query, api_key)[:3]

    all_urls = set()  # використовуємо множину для унікальних URL
    all_content = ""
    
    # Створюємо основний запис пошуку
    new_search = Search(
        query=query, 
        search_type="deep", 
        response="Пошук триває... Збираємо інформацію з джерел."
    )
    session.add(new_search)
    session.commit()
    search_id = new_search.id

    # 2. Шукаємо URL (обмежуємо до 5 на запит)
    for sub_query in sub_queries:
        search_results = search_duckduckgo(sub_query, num_results=5)
        for result in search_results:
            all_urls.add(result['url'])

    successful_pages = 0
    
    # Створюємо нову сесію для обробки сторінок, щоб запобігти проблемам з від'єднаними об'єктами
    if len(all_urls) > 0:
        for url in all_urls:
            try:
                # Стандартні значення за замовчуванням
                title = url  # URL як заголовок за замовчуванням
                favicon_url = "/static/default-favicon.png"  # іконка за замовчуванням
                content = ""
                
                # Спроба отримати контент
                content = parse_page_content(url)
                
                # Пропускаємо, якщо контент занадто короткий
                if len(content.strip()) < 30:
                    print(f"Занадто короткий контент для {url}")
                    continue
                
                # Спроба отримати заголовок (щоб не блокуватись, використовуємо прості заголовки)
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    response = requests.get(url, headers=headers, timeout=5)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.content, 'html.parser')
                        if soup.title and soup.title.string:
                            title = soup.title.string.strip()
                except Exception as e:
                    logging.warning(f"Не вдалося отримати заголовок для {url}: {e}")
                
                # Спроба отримати іконку
                try:
                    favicon_url = get_favicon(url)
                except Exception as e:
                    logging.warning(f"Не вдалося отримати іконку для {url}: {e}")
                
                # Додаємо контент до загального вмісту для звіту
                all_content += f"\n\n# {title}\n\n{content}"
                successful_pages += 1
                
                # Зберігаємо в БД
                try:
                    # Використовуємо ту саму сесію, що створила new_search
                    new_page = WebPage(
                        search_id=search_id, 
                        url=url, 
                        title=title, 
                        icon_url=favicon_url, 
                        content=content
                    )
                    session.add(new_page)
                    session.commit()
                except Exception as e:
                    logging.error(f"Помилка при збереженні в БД для {url}: {e}")
                
            except Exception as e:
                logging.error(f"Глобальна помилка при обробці {url}: {e}")
    
    # Відлагоджувальна інформація
    print(f"Успішно оброблено сторінок: {successful_pages} з {len(all_urls)}")
    
    # 4. Генеруємо звіт
    if successful_pages == 0:
        # Якщо жодна сторінка не оброблена успішно
        error_message = f"""## Результати пошуку за запитом "{query}"

На жаль, не вдалося отримати корисний вміст з веб-сторінок. Можливі причини:
- Сайти блокують автоматичні запити
- Проблеми з підключенням до Інтернету
- Обмежений доступ до контенту

Спробуйте наступне:
1. Використайте більш конкретний пошуковий запит
2. Спробуйте звичайний (не глибокий) пошук
3. Перевірте підключення до Інтернету
"""
        new_search.response = error_message
        session.commit()
        return search_id
    
    # Якщо є контент, генеруємо звіт за допомогою Gemini
    if api_key:
        # Обмежуємо розмір контенту для API
        max_content_length = 30000
        trimmed_content = all_content[:max_content_length] if len(all_content) > max_content_length else all_content
        
        system_prompt = """Ти - DeepScout AI, компактний аналітик.

ЗАВДАННЯ: Створити короткий звіт на основі зібраної інформації.

ПРИНЦИПИ:
1. Аналізуй ТІЛЬКИ надану інформацію
2. Структуруй коротко та зрозуміло
3. Використовуй мову запиту
4. Тільки ключові факти

ФОРМАТ:
- Основне (2-3 речення)
- Ключові пункти (3-5 коротких)
- Висновок (1 речення)

ЗАБОРОНЕНО:
- Фрази "згідно з джерелами"
- Довгі пояснення
- Повторення інформації"""

        prompt = f"""{system_prompt}

ТЕМА: "{query}"
ЗІБРАНА ІНФОРМАЦІЯ: {trimmed_content}

Створи компактний звіт з головними фактами."""
        
        try:
            gemini_report = get_gemini_response(prompt, api_key, detailed=False)
            new_search.response = gemini_report
        except Exception as e:
            logging.error(f"Помилка при отриманні відповіді Gemini: {e}")
            new_search.response = f"Сталася помилка при генерації звіту: {str(e)}\n\nЗібраний контент:\n{trimmed_content[:1000]}..."
        
        session.commit()
    else:
        # Якщо API ключ не налаштовано
        new_search.response = "Помилка: Не налаштовано API key для Gemini. Звіт не може бути згенерований."
        session.commit()

    return search_id