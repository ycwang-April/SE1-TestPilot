FROM python:3.13-slim
RUN pip install --no-cache-dir "pytest>=8,<10" "pytest-cov>=6,<8"
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
CMD ["python", "-m", "pytest", "--version"]
