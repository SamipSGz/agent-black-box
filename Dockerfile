FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the SRE copilot service. Override `command` to run the agent.
EXPOSE 8099
CMD ["python", "-m", "copilot.webhook_server"]
