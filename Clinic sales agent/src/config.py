import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash')
REQUEST_DELAY = float(os.getenv('REQUEST_DELAY', '1.5'))
MAX_PAGES_PER_CLINIC = int(os.getenv('MAX_PAGES_PER_CLINIC', '10'))
MAX_TEXT_CHARS = int(os.getenv('MAX_TEXT_CHARS', '12000'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '15'))

_base = os.path.dirname(__file__)
GOOGLE_CREDENTIALS_PATH = os.path.join(_base, '..', os.getenv('GOOGLE_CREDENTIALS_PATH', 'credentials/gmail-credentials.json'))
GOOGLE_TOKEN_PATH = os.path.join(_base, '..', os.getenv('GOOGLE_TOKEN_PATH', 'credentials/token.json'))
