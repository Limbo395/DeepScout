import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

def get_favicon(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    
    try:
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        icon_link = soup.find("link", rel="icon") or \
                    soup.find("link", rel="shortcut icon") or \
                    soup.find("link", rel="apple-touch-icon")

        if icon_link and icon_link.get('href'):
            favicon_url = icon_link['href']
            favicon_url = urljoin(url, favicon_url)
            return favicon_url

        favicon_url = urljoin(url, '/favicon.ico')
        try:
            test_response = requests.head(favicon_url, timeout=5, headers=headers)
            if test_response.status_code == 200:
                return favicon_url
        except:
            pass

        return f"https://www.google.com/s2/favicons?domain={url}"

    except requests.exceptions.RequestException as e:
        print(f"Помилка при отриманні іконки для {url}: {e}")
        return "/static/default-favicon.png"
    except Exception as e:
        print(f"Інша помилка при отриманні іконки: {e}")
        return "/static/default-favicon.png"

def parse_page_content(url):
    """
    Покращена функція для отримання контенту сторінки з різними методами завантаження.
    Спочатку пробує через requests, якщо не виходить - через selenium.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://www.google.com/'
    }
    
    # Пробуємо через requests
    try:
        response = requests.get(url, timeout=15, headers=headers)
        response.raise_for_status()
        content = extract_text_from_html(response.content)
        
        # Якщо контент не порожній, повертаємо його
        if content and len(content.strip()) > 50:
            return content
    except Exception as e:
        print(f"Не вдалося отримати контент через requests для {url}: {e}")
    
    # Якщо requests не спрацював, використовуємо selenium
    try:
        content = parse_with_selenium(url)
        return content
    except Exception as e:
        print(f"Не вдалося отримати контент через selenium для {url}: {e}")
    
    # Фоллбек - повертаємо хоч якусь інформацію
    return f"Інформація з {url} недоступна через обмеження сайту. URL: {url}"

def extract_text_from_html(html_content):
    """Покращений екстрактор тексту з HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Видаляємо всі скрипти, стилі та інші непотрібні елементи
    for element in soup(['script', 'style', 'head', 'header', 'footer', 'nav']):
        element.extract()
    
    # Спроба 1: Шукаємо основний контент за поширеними класами
    main_content = soup.find(['main', 'article', 'div'], 
                            class_=['content', 'main-content', 'article-content', 'post-content', 
                                    'entry-content', 'page-content', 'main'])
    
    if main_content:
        return main_content.get_text(separator='\n', strip=True)
    
    # Спроба 2: Шукаємо всі абзаци
    paragraphs = soup.find_all('p')
    if paragraphs:
        text = '\n\n'.join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
        if len(text) > 100:
            return text
    
    # Спроба 3: Беремо весь текст з body
    body = soup.find('body')
    if body:
        return body.get_text(separator='\n', strip=True)
    
    # Якщо нічого не знайдено, повертаємо весь текст
    return soup.get_text(separator='\n', strip=True)

def parse_with_selenium(url):
    """Отримання контенту за допомогою Selenium, що може обійти захист від скрапінгу."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        driver.get(url)
        # Чекаємо, щоб сторінка завантажилась
        time.sleep(3)
        
        # Скролимо, щоб завантажити ліниве завантаження
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        
        # Отримуємо весь контент сторінки
        page_source = driver.page_source
        driver.quit()
        
        # Обробляємо отриманий HTML
        return extract_text_from_html(page_source)
    except Exception as e:
        if driver:
            driver.quit()
        raise e