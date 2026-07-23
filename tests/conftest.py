import os

os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"
os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
