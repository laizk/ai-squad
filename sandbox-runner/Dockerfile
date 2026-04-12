FROM python:3.12-slim

WORKDIR /app

# Install test tooling available inside the sandbox
RUN pip install --no-cache-dir pytest==8.4.2

COPY runner.py .

CMD ["python", "-u", "runner.py"]
