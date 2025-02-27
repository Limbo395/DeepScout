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

def get_gemini_response(query, api_key):
    if not api_key:
        return "Помилка: Не налаштовано API key для Gemini."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # Improved prompt for balanced and informative responses
    prompt = f"""Відповідь на запит: "{query}"

    Інструкції:
    1. Визнач мову запиту і відповідай тією ж мовою
    2. Якщо це запит про значення (наприклад, "торт", "програмування") - поясни, що це таке, і надай короткий, але інформативний огляд, включаючи основні різновиди або категорії
    3. Якщо це конкретне запитання - надай чітку відповідь з підтверджуючими деталями
    4. Не використовуй метамову типу "Відповідно до...", "На основі інформації..." тощо 
    5. Форматуй відповідь структуровано, використовуючи заголовки тільки за потреби
    6. Відповідь має бути змістовною, але лаконічною
    7. Не починай з "Це..." або подібних загальних вступів
    8. Уникай кольорових гіперпосилань
    """
    
    response = model.generate_content(prompt)
    return response.text.strip()

def generate_sub_queries(query, api_key, num_queries=5):
    """
    Generates related search queries using Gemini.
    Improved prompt to generate more precise sub-queries.
    """
    if not api_key:
        return ["Помилка: Не налаштовано API key для Gemini."]

    prompt = (
        f"На основі запиту '{query}', створи {num_queries} пошукових запитів, які допоможуть зібрати вичерпну інформацію. "
        f"Поверни ТІЛЬКИ список запитів без нумерації чи пояснень - по одному на рядок. "
        f"Визнач мову запиту і використовуй ту саму мову."
    )
    sub_queries = get_gemini_response(prompt, api_key).splitlines()
    
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
    Performs deep search: generates sub-queries, collects URLs, extracts content and saves to DB.
    Improved prompt for better deep research reports.
    """

    # 1. Generate Sub-Queries
    sub_queries = generate_sub_queries(query, api_key)

    all_urls = set()  # use a set to avoid duplicates
    all_content = ""

    # Create main search entry
    new_search = Search(query=query, search_type="deep", response="")
    session.add(new_search)
    session.commit()
    search_id = new_search.id

    # 2. Search and Collect URLs
    for sub_query in sub_queries:
        search_results = search_duckduckgo(sub_query, num_results=10)
        for result in search_results:
            all_urls.add(result['url'])

    # 3. Extract Content and Save to DB
    for url in all_urls:
        try:
            title = url  # fallback title
            favicon_url = ""
            try:
                favicon_url = get_favicon(url)
            except Exception as e:
                logging.error(f"Помилка при отриманні іконки для {url}: {e}")
            content = ""
            try:
                content = parse_page_content(url)
            except Exception as e:
                logging.error(f"Помилка при завантаженні сторінки {url}: {e}")

            # Try to get real title
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
            except Exception as e:
                logging.error(f"Помилка при завантаженні заголовку для {url}: {e}")

            all_content += f"\n\n# {title}\n\n{content}"

            new_page = WebPage(search_id=search_id, url=url, title=title, icon_url=favicon_url, content=content)
            session.add(new_page)
            session.commit()
        except Exception as e:
            logging.error(f"Помилка при обробці {url}: {e}")

    # 4. Generate Report
    if api_key:
        # Improved deep research prompt for more extensive and structured reports
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
        {all_content}
        """
        
        gemini_report = get_gemini_response(prompt, api_key)
        new_search.response = gemini_report
        session.commit()
    else:
        gemini_report = "Помилка: Не налаштовано API key для Gemini. Звіт не може бути згенерований."
        new_search.response = gemini_report
        session.commit()

    return search_id