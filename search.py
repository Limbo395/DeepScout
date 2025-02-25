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
    
    # Оновлений промпт для стилю пошукової системи
    prompt = f"""Дій як пошукова система: "{query}"

    Інструкції для відповіді:
    1. Якщо це пошуковий запит - поясни значення слів, термінів та концепцій
    2. Якщо це питання - дай чітку та інформативну відповідь
    3. Додай визначення ключових термінів
    4. Використовуй структурований формат з заголовками і підзаголовками
    5. Пиши мовою якою поставив запитання користувач
    6. відповідь має бути маленькою
    """
    
    response = model.generate_content(prompt)
    return response.text.strip()

def generate_sub_queries(query, api_key, num_queries=5):
    """
    Generates related search queries using Gemini.
    Інструкція: поверни лише список запитів (по одному на рядок), без зайвих пояснень.
    """
    if not api_key:
        return ["Помилка: Не налаштовано API key для Gemini."]

    prompt = (
        f"На основі запиту '{query}', згенеруй {num_queries} різних релевантних пошукових запитів. "
        "Відповідь повинна містити тільки список запитів, кожен з нового рядка, без додаткових пояснень."
    )
    sub_queries = get_gemini_response(prompt, api_key).splitlines()
    return sub_queries[:num_queries]

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
    Потім аналізує зібрану інформацію і генерує детальний звіт, де відповідь містить тільки текст звіту.
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
        prompt = f"""Дій як пошукова система. Проаналізуй надану інформацію та створи детальний звіт про: "{query}"

        Інструкції:
        1. Надай вичерпне пояснення теми/питання
        2. Визнач та поясни ключові терміни
        3. Структуруй інформацію за релевантністю
        4. Використовуй чіткий та інформативний стиль, використовуючи заголовки і підзаголовки
        5. Пиши мовою якою поставив запитання користувач
        6. Відповідь має бути великою і інформативною


        Інформація для аналізу:
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