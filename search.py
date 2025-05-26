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

def get_gemini_response(query, api_key, detailed=False):
    if not api_key:
        return "Помилка: Не налаштовано API key для Gemini."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # Enhanced prompt for regular searches to provide more detailed responses
        if detailed:
            enhanced_query = f"""Надай детальну відповідь на запит: {query}
            
            Інструкції:
            1. Визнач мову запиту і використовуй її у відповіді
            2. Надай повну і детальну інформацію з різних сторін питання
            3. Структуруй відповідь для кращого розуміння
            4. Використовуй приклади, аналогії та пояснення, де це необхідно
            5. Уникай надто коротких і поверхневих відповідей
            """
            query = enhanced_query
        
        # Generate response
        response = model.generate_content(query)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Error in get_gemini_response: {e}")
        return f"Помилка при отриманні відповіді від Gemini: {str(e)}"

def generate_sub_queries(query, api_key, num_queries=5):
    """
    Generates related search queries using Gemini.
    Improved prompt to generate more precise sub-queries.
    """
    if not api_key:
        return ["Помилка: Не налаштовано API key для Gemini."]

    prompt = (
        f"На основі запиту '{query}', створи {num_queries} пошукових запитів, які допоможуть зібрати вичерпну інформацію. "        f"Поверни ТІЛЬКИ список запитів без нумерації чи пояснень - по одному на рядок. "
        f"Визнач мову запиту і використовуй ту саму мову."
    )
    sub_queries = get_gemini_response(prompt, api_key, detailed=False).splitlines()
    
    # Filter out any lines that might be empty or contain unwanted characters
    filtered_queries = [q.strip() for q in sub_queries if q.strip()]
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
        
        prompt = f"""Створи детальний аналітичний звіт на тему: "{query}"

        Інструкції:
        1. Визнач мову запиту і використовуй її у відповіді
        2. Організуй інформацію в логічну структуру з розділами та підрозділами
        3. Використовуй фактичну інформацію з наданих джерел
        4. Аналізуй різні аспекти теми, включаючи визначення, історію, різновиди, поширені питання тощо
        5. Уникай фраз типу "Згідно з наданою інформацією" або "На основі джерел"
        6. Не використовуй кольорові гіперпосилання
        7. Подавай інформацію об'єктивно, з увагою до деталей
        8. Підготуй комплексний, інформативний та структурований звіт
        
        Інформація з джерел:
        {trimmed_content}        """
        
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