# Use a minimal Python 3.11 image as the base
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the source code and dependencies file to the container
COPY src /app/src/
COPY requirements.txt /app/

# Install required dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables (these can be overridden in Fly.io Dashboard)
ENV BOT_TOKEN=""
ENV ADMIN_ID=""
ENV ACCOUNT_INFO=""

# Run the bot script with the correct path
CMD ["python", "src/main.py"]
