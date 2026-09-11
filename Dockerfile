FROM python:3.11-slim

# Prevent .pyc files and enable unbuffered logging (useful for Render logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Quiz JSON files are stored under quiz_data/quizzes at runtime.
# NOTE: Render's disk is ephemeral on redeploy unless you attach a paid
# persistent disk mounted at this path — see note below.
RUN mkdir -p quiz_data/quizzes

CMD ["python", "bot.py"]
