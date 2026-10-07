# Python 3.10 (same as .python-version)
FROM python:3.10

WORKDIR /usr/src/travian-bot

# Copy build dependencies to workdir
COPY requirements*.txt ./

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Run bot on container start
ENTRYPOINT [ "python", "-u", "bot/bot.py" ]
