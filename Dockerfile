FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -g 10001 roy && useradd -u 10001 -g roy -m roy
COPY --chown=roy:roy engine.py bot.py games.py tavern.py characters.py interface.py feature_interface.py character_interface.py instance_lock.py ./
COPY --chown=roy:roy assets/ ./assets/
COPY --chown=roy:roy catalog/ ./catalog/
RUN mkdir -p /app/data && chown roy:roy /app/data
USER roy
CMD ["python", "bot.py"]
