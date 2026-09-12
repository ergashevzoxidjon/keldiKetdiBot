import os
from dotenv import load_dotenv

print("CWD:", os.getcwd())
print("__file__ dir:", os.path.dirname(os.path.abspath(__file__)))

before = os.getenv("WEBAPP_URL")
print("WEBAPP_URL before load_dotenv():", repr(before))

result = load_dotenv()
print("load_dotenv() returned:", result)

after = os.getenv("WEBAPP_URL")
print("WEBAPP_URL after load_dotenv():", repr(after))
print("BOT_TOKEN after load_dotenv():", repr(os.getenv("BOT_TOKEN")))

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
print(".env path checked:", env_path)
print(".env exists:", os.path.exists(env_path))
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        print("--- .env content ---")
        print(f.read())
