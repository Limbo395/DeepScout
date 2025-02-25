import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def get_favicon(url):
    try:
        response = requests.get(url, timeout=10)
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
            test_response = requests.head(favicon_url, timeout=5)
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
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        for script in soup(["script", "style", "head", "meta", "[document]"]):
            script.extract()

        text_elements = soup.find_all(['p', 'article', 'div'], class_=['content', 'article-body', 'post-body'])
        text = ""
        for element in text_elements:
            text += element.get_text(separator='\n', strip=True) + "\n\n"

        return text

    except requests.exceptions.RequestException as e:
        print(f"Помилка при завантаженні сторінки {url}: {e}")
        return ""
    except Exception as e:
        print(f"Інша помилка при парсингу сторінки {url}: {e}")
        return ""